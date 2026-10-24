"""
ingest_url.py — Phase 2 remainder: ingest a public web page as a document.

Safety is the whole point of this module: fetching a user-supplied URL
server-side is an SSRF vector, so the guard below runs *before* any
request is made:

* Only ``http``/``https`` URLs, with a hostname (no bare IPs in the
  path, no credentials in the URL).
* The hostname is resolved and *every* returned address is checked:
  literal and resolved IPs that are private, loopback, link-local,
  reserved, multicast or unspecified are rejected. This covers both
  ``http://127.0.0.1/...`` and DNS rebinding to a private address
  (a DNS name resolving to both a public and a private address is
  rejected because the private one is in the list).
* No redirects are followed: a 3xx response is rejected rather than
  chased to a possibly-private destination.
* 15s timeout, 2 MB body cap, and only ``text/html`` / ``text/plain``
  content types are accepted.

HTML is reduced to text with a stdlib-only stripper (tags removed,
entities unescaped, whitespace collapsed). It is not a full reader
mode — boilerplate (nav, footers) may survive — and that limit is
stated in the endpoint response, not hidden.
"""

from __future__ import annotations

import html as html_lib
import ipaddress
import re
import socket
from urllib.parse import urlparse

MAX_BODY_BYTES = 2_000_000
FETCH_TIMEOUT_SECONDS = 15.0


class IngestUrlError(ValueError):
    """Rejected URL or failed fetch; the message is safe to return."""


def _is_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_url(url: str) -> str:
    """Validate a URL for server-side fetching. Returns the hostname.

    Raises IngestUrlError on any rejection. Hostname resolution uses
    the system resolver; a name that does not resolve is rejected.
    """
    if not url or not isinstance(url, str):
        raise IngestUrlError("A URL is required")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise IngestUrlError("Only http:// and https:// URLs can be ingested")
    if parsed.username or parsed.password:
        raise IngestUrlError("URLs with credentials cannot be ingested")
    host = parsed.hostname
    if not host:
        raise IngestUrlError("URL must have a hostname")
    # Literal IP: check directly, no DNS needed. (IngestUrlError is a
    # ValueError subclass, so the check must not sit inside the
    # try/except that treats ValueError as "not an IP".)
    try:
        ipaddress.ip_address(host)
        is_literal_ip = True
    except ValueError:
        is_literal_ip = False
    if is_literal_ip:
        if not _is_public_ip(host):
            raise IngestUrlError("URLs pointing at private or local addresses cannot be ingested")
        return host
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise IngestUrlError("Hostname could not be resolved") from None
    addresses = {info[4][0] for info in infos if info[4]}
    if not addresses:
        raise IngestUrlError("Hostname could not be resolved")
    if not all(_is_public_ip(a) for a in addresses):
        raise IngestUrlError("URLs pointing at private or local addresses cannot be ingested")
    return host


_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def html_to_text(body: str) -> str:
    """Strip script/style/tags, unescape entities, collapse whitespace."""
    text = _TAG_RE.sub(" ", body)
    text = _HTML_TAG_RE.sub(" ", text)
    text = html_lib.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def slug_from_url(url: str) -> str:
    """A readable filename for an ingested page, e.g. example.com-docs-guide."""
    parsed = urlparse(url)
    host = parsed.hostname or "page"
    path = re.sub(r"[^a-zA-Z0-9]+", "-", (parsed.path or "").strip("/")).strip("-")
    name = f"{host}-{path}" if path else host
    return (name[:80] or "page") + ".txt"


def normalize_url(url: str) -> str:
    """Canonical form for dedupe: lowercase scheme/host, fragment
    stripped, default ports dropped, trailing slash removed except
    for the bare root path. Query strings are kept (they change the
    page); a URL that fails to parse is returned stripped."""
    try:
        parsed = urlparse((url or "").strip())
        scheme = (parsed.scheme or "https").lower()
        host = (parsed.hostname or "").lower()
        if not host:
            return (url or "").strip()
        port = parsed.port
        if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
            port = None
        netloc = f"{host}:{port}" if port else host
        path = parsed.path or ""
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
        out = f"{scheme}://{netloc}{path}"
        if parsed.query:
            out += f"?{parsed.query}"
        return out
    except (ValueError, TypeError):
        return (url or "").strip()


async def fetch_page_text(url: str) -> tuple[str, str]:
    """SSRF-guarded fetch shared by the knowledge ingest endpoint and
    notebook ingest-on-add. Returns (plain text, content type).
    Raises IngestUrlError on rejection and ValueError/RuntimeError
    subclasses on fetch/extraction failure; callers translate those
    into HTTP statuses (or, for notebook add, a failed-ingest note
    that never blocks creating the source row)."""
    import httpx

    validate_url(url)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(FETCH_TIMEOUT_SECONDS, connect=8.0),
            follow_redirects=False,
        ) as client:
            resp = await client.get(url, headers={"User-Agent": "Sangam/1.0 (+local-first)"})
    except Exception as exc:  # noqa: BLE001 — network failure is a fetch failure
        raise RuntimeError(f"Could not fetch URL ({exc})") from exc
    if resp.status_code in (301, 302, 303, 307, 308):
        raise IngestUrlError("Redirects are not followed for ingestion")
    if resp.status_code != 200:
        raise RuntimeError(f"URL returned HTTP {resp.status_code}")
    content_type = (resp.headers.get("content-type") or "").lower()
    if "text/html" not in content_type and "text/plain" not in content_type:
        raise IngestUrlError(f"Unsupported content type: {content_type or 'unknown'}")
    body = resp.content[: MAX_BODY_BYTES + 1]
    if len(body) > MAX_BODY_BYTES:
        raise IngestUrlError("Page exceeds 2 MB ingestion limit")
    if "text/html" in content_type:
        text = html_to_text(body.decode("utf-8", errors="replace"))
    else:
        text = body.decode("utf-8", errors="replace").strip()
    if not text:
        raise IngestUrlError("No readable text found on the page")
    return text, content_type
