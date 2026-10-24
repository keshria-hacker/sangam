"""
crawl_job.py — Wave-2 deep-knowledge: BFS deep-crawl job (crawl4ai
pipeline shape, Sangam-native).

Sangam previously had no deep crawler: single-URL ingest plus a
shallow same-host static workflow node (depth 1, no JS). This module
is the crawl half:

* BFS frontier with depth/page caps, same-domain filter (external
  links only when ``include_external`` is set), and a scorer
  (keyword relevance + path-depth score with optimal depth 3, the
  crawl4ai defaults reduced to two plug-in points).
* SSRF gating: every discovered URL passes ``ingest_url.validate_url``
  unless ``allow_local`` is set — which exists ONLY for tests
  against a local fixture server and for explicitly local docs; the
  knowledge route defaults it off and documents it as such.
* robots.txt respected per host (Disallow/Allow, longest-match
  wins, ``*`` agent group; a missing/unfetchable robots file means
  allowed — fail-open on the robots fetch itself, never on the SSRF
  check).
* Runs-centre mirroring is done by the caller (knowledge route):
  this module returns a summary; it does not own the RunStore.
* Indexing is injected (``indexer`` callable) so tests can record
  pages without a vector store, and production passes the RAG
  indexer. CrawlPage rows persist ``parent_url`` provenance per
  page; the route exposes them.

Fetching: the default fetcher is static httpx (fast, testable).
``browser_fetcher`` reuses the existing Node Playwright driver
(browser_agent.run_browser_actions: navigate + extract) for JS-rendered
text; link discovery still uses a static fetch, because the driver
has no ``links`` action yet — that driver extension is logged for
the parent rather than faked here. Approval gating lives in the
route (``approved: true`` required), not in this module.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

DEFAULT_MAX_DEPTH = 2
DEFAULT_MAX_PAGES = 20
OPTIMAL_DEPTH = 3
USER_AGENT = "Sangam/1.0 (+local-first)"

_SKIP_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".pdf", ".zip",
    ".gz", ".mp4", ".mp3", ".woff", ".woff2", ".ttf", ".css", ".js",
)


class CrawlError(ValueError):
    """A crawl fetch/validation failure; message is safe to return."""


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    seed_url: Mapped[str] = mapped_column(String(512))
    max_depth: Mapped[int] = mapped_column(Integer, default=DEFAULT_MAX_DEPTH)
    max_pages: Mapped[int] = mapped_column(Integer, default=DEFAULT_MAX_PAGES)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    pages_indexed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class CrawlPage(Base):
    __tablename__ = "crawl_pages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(32), ForeignKey("crawl_jobs.id"), index=True)
    url: Mapped[str] = mapped_column(String(512))
    parent_url: Mapped[str] = mapped_column(String(512), default="")
    depth: Mapped[int] = mapped_column(Integer, default=0)
    file_id: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


def crawl_job_out(row: CrawlJob) -> dict:
    return {"id": row.id, "seed_url": row.seed_url, "max_depth": row.max_depth,
            "max_pages": row.max_pages, "status": row.status,
            "pages_indexed": row.pages_indexed, "error": row.error,
            "created_at": row.created_at.isoformat() if row.created_at else None}


def crawl_page_out(row: CrawlPage) -> dict:
    return {"id": row.id, "job_id": row.job_id, "url": row.url,
            "parent_url": row.parent_url, "depth": row.depth,
            "file_id": row.file_id, "title": row.title,
            "created_at": row.created_at.isoformat() if row.created_at else None}


# ---------------------------------------------------------------- scoring

def score_url(url: str, keywords: list[str], depth: int,
              optimal_depth: int = OPTIMAL_DEPTH) -> float:
    """Keyword relevance + path-depth score (crawl4ai's two scorers,
    reduced). Keyword hits count in the path/query tokens; depth
    scores 1.0 at the optimal depth and decays linearly away from
    it. A page with no keyword hits still scores on depth alone, so
    keyword-free crawls explore breadth-first instead of stalling."""
    haystack = (urlparse(url).path + " " + urlparse(url).query).lower()
    tokens = set(re.findall(r"[a-z0-9]+", haystack))
    kw_hits = sum(1 for kw in keywords if kw.lower() in tokens or kw.lower() in haystack)
    kw_score = (kw_hits / len(keywords)) if keywords else 0.5
    depth_score = max(0.0, 1.0 - abs(depth - optimal_depth) / (optimal_depth + 1.0))
    if keywords:
        return 0.7 * kw_score + 0.3 * depth_score
    return depth_score


def same_domain(url: str, seed_host: str) -> bool:
    return (urlparse(url).hostname or "").lower() == seed_host.lower()


def url_allowed_by_filters(url: str, seed_host: str, include_external: bool) -> bool:
    """Same-domain filter + binary/asset extension skip. Fragments
    are stripped by the caller before this runs."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    if not include_external and not same_domain(url, seed_host):
        return False
    if parsed.path.lower().endswith(_SKIP_EXTENSIONS):
        return False
    return True


# ---------------------------------------------------------------- robots

def robots_allowed(robots_txt: str | None, path: str, agent: str = "Sangam") -> bool:
    """robots.txt check: the most specific matching group's rules
    win; within a group the longest Allow/Disallow match wins (ties:
    Allow wins). No robots file, or no matching group, means allowed."""
    if not robots_txt:
        return True
    groups: list[tuple[list[str], list[tuple[str, bool]]]] = []
    current_agents: list[str] = []
    current_rules: list[tuple[str, bool]] = []
    for raw_line in robots_txt.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if current_agents or current_rules:
                groups.append((current_agents, current_rules))
                current_agents, current_rules = [], []
            current_agents.append(value)
        elif key in ("allow", "disallow") and value:
            current_rules.append((value, key == "allow"))
    if current_agents or current_rules:
        groups.append((current_agents, current_rules))
    matching = None
    for agents, rules in groups:
        if "*" in agents:
            matching = rules
        if agent in agents or agent.lower() in [a.lower() for a in agents]:
            matching = rules
            break
    if matching is None:
        return True
    best_len, best_allow = -1, True
    for pattern, allow in matching:
        pat = pattern.rstrip("*")
        if path.startswith(pat) and len(pat) > best_len:
            best_len, best_allow = len(pat), allow
        elif path.startswith(pat) and len(pat) == best_len and allow:
            best_allow = True
    return best_allow


# ---------------------------------------------------------------- links

class _LinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                absolute = urljoin(self.base_url, href).split("#", 1)[0]
                if absolute and absolute not in self.links:
                    self.links.append(absolute)
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data.strip())


def parse_links(html: str, base_url: str) -> tuple[list[str], str]:
    parser = _LinkParser(base_url)
    parser.feed(html)
    return parser.links, " ".join(p for p in parser.title_parts if p).strip()


# ---------------------------------------------------------------- fetchers

async def fetch_page_http(
    url: str, robots_cache: dict[str, str | None] | None = None,
    allow_local: bool = False,
) -> dict | None:
    """Static fetch: SSRF validation (or scheme/host check when
    ``allow_local`` is set for fixture/local docs), robots check,
    no redirects, 2 MB cap, html/plain only. Returns
    {url, text, links, title} or None when the page is unusable
    (non-200, robots-disallowed, wrong type) — never raises for a
    single bad page, so one bad page cannot kill a crawl."""
    import httpx

    from .ingest_url import (
        FETCH_TIMEOUT_SECONDS,
        MAX_BODY_BYTES,
        IngestUrlError,
        html_to_text,
    )

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if not allow_local:
        from .ingest_url import validate_url

        try:
            validate_url(url)
        except IngestUrlError:
            return None
    host = parsed.hostname
    netloc = parsed.netloc
    robots_cache = robots_cache if robots_cache is not None else {}
    if netloc not in robots_cache:
        robots_txt = None
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(8.0, connect=5.0), follow_redirects=False,
            ) as client:
                resp = await client.get(
                    f"{parsed.scheme}://{netloc}/robots.txt",
                    headers={"User-Agent": USER_AGENT})
                if resp.status_code == 200:
                    robots_txt = resp.text
        except Exception:  # noqa: BLE001 — robots fetch failure = allowed
            robots_txt = None
        robots_cache[netloc] = robots_txt
    if not robots_allowed(robots_cache.get(netloc), parsed.path or "/"):
        return None
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(FETCH_TIMEOUT_SECONDS, connect=8.0),
            follow_redirects=False,
        ) as client:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT})
    except Exception:  # noqa: BLE001 — one bad page never kills the crawl
        return None
    if resp.status_code != 200:
        return None
    content_type = (resp.headers.get("content-type") or "").lower()
    if "text/html" not in content_type and "text/plain" not in content_type:
        return None
    body = resp.content[: MAX_BODY_BYTES + 1]
    if len(body) > MAX_BODY_BYTES:
        return None
    if "text/html" in content_type:
        raw = body.decode("utf-8", errors="replace")
        text = html_to_text(raw)
        links, title = parse_links(raw, url)
    else:
        text = body.decode("utf-8", errors="replace").strip()
        links, title = [], ""
    if not text:
        return None
    return {"url": url, "text": text, "links": links, "title": title}


def browser_fetcher(robots_cache: dict | None = None, profile_dir=None):
    """JS-rendered fetch via the existing Node Playwright driver
    (browser_agent.run_browser_actions: navigate + extract). Link
    discovery still uses a static fetch — the driver has no ``links``
    action yet (see module docstring). Returns the same shape as
    ``fetch_page_http`` or None. Import is lazy so crawls without a
    browser never pay for the driver import."""
    import tempfile

    async def _fetch(page_url: str) -> dict | None:
        from .browser_agent import run_browser_actions

        profile = profile_dir or tempfile.mkdtemp(prefix="sangam-crawl-profile-")
        try:
            result = await asyncio.to_thread(
                run_browser_actions,
                "automation",
                [{"action": "navigate", "url": page_url},
                 {"action": "extract"}],
                profile,
            )
            results = result.results
        except Exception:  # noqa: BLE001 — driver unavailable = page skipped
            return None
        texts = [str(r.get("text", "")) for r in results if r.get("ok") and r.get("text")]
        text = "\n".join(texts).strip()
        if not text:
            return None
        static = await fetch_page_http(page_url, robots_cache=robots_cache)
        links = static["links"] if static else []
        return {"url": page_url, "text": text, "links": links, "title": ""}
    return _fetch


# ---------------------------------------------------------------- BFS job

async def run_crawl(
    seed_url: str,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_pages: int = DEFAULT_MAX_PAGES,
    keywords: list[str] | None = None,
    include_external: bool = False,
    fetcher=None,
    indexer=None,
    validate_discovered: bool = True,
) -> dict:
    """BFS deep crawl. ``fetcher(url) -> page dict | None`` defaults
    to ``fetch_page_http``; ``indexer(url, text, parent_url, depth)
    -> file_id | None`` defaults to a no-op (pages are still counted
    and returned). Returns {seed_url, pages, indexed, errors} where
    each page carries url/parent_url/depth/file_id/title/chars.
    Frontier order per level is score-descending, capped by the
    remaining page budget — crawl4ai's top-by-score frontier rule."""
    from .ingest_url import validate_url, IngestUrlError

    keywords = keywords or []
    seed_host = (urlparse(seed_url).hostname or "").lower()
    if not seed_host:
        raise CrawlError("Seed URL must have a hostname")
    if fetcher is None:
        robots_cache: dict[str, str | None] = {}

        async def _default_fetch(url: str) -> dict | None:
            return await fetch_page_http(url, robots_cache=robots_cache)

        fetcher = _default_fetch
    visited: set[str] = set()
    frontier: list[tuple[str, str, int]] = [(seed_url, "", 0)]
    pages: list[dict] = []
    errors: list[str] = []
    while frontier and len(pages) < max_pages:
        level = frontier
        frontier = []
        candidates: list[tuple[float, str, str, int]] = []
        for url, parent_url, depth in level:
            if url in visited or len(pages) >= max_pages:
                continue
            visited.add(url)
            try:
                page = await fetcher(url)
            except Exception as exc:  # noqa: BLE001 — per-page failure
                errors.append(f"{url}: {exc}")
                continue
            if page is None:
                continue
            text = page.get("text", "")
            file_id = None
            if indexer is not None:
                try:
                    file_id = indexer(url, text, parent_url, depth)
                except Exception as exc:  # noqa: BLE001 — index failure noted
                    errors.append(f"{url}: index failed ({exc})")
            pages.append({"url": url, "parent_url": parent_url, "depth": depth,
                          "file_id": file_id or "", "title": page.get("title", ""),
                          "chars": len(text), "text": text})
            if depth < max_depth and len(pages) + len(frontier) < max_pages:
                for link in page.get("links", []):
                    if link in visited:
                        continue
                    if not url_allowed_by_filters(link, seed_host, include_external):
                        continue
                    if not include_external:
                        # SSRF gate on every discovered URL (public
                        # crawls). Fixture crawls pass their own
                        # fetcher with validate_discovered=False,
                        # which owns its validation.
                        if validate_discovered:
                            try:
                                validate_url(link)
                            except IngestUrlError:
                                continue
                    candidates.append(
                        (score_url(link, keywords, depth + 1), link, url, depth + 1))
        candidates.sort(key=lambda c: c[0], reverse=True)
        remaining = max_pages - len(pages)
        frontier = [(link, parent, d) for _, link, parent, d in candidates[:remaining]]
    return {"seed_url": seed_url, "pages": pages,
            "indexed": sum(1 for p in pages if p["file_id"]),
            "errors": errors}
