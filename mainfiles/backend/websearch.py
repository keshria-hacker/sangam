"""Real web search for the chat platform.

Out of the box this uses DuckDuckGo's Lite HTML endpoint (no API key
required) so web search works immediately. If the operator configures a
`WEB_SEARCH_PROVIDER` + `WEB_SEARCH_API_KEY` (tavily or brave) in `.env`,
that higher-quality provider is used instead. Every path degrades gracefully:
failures raise a clear ``RuntimeError`` rather than silently returning
nothing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape

import httpx

from backend.config import settings


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str

    def to_context(self) -> str:
        return f"- {self.title} ({self.url}): {self.snippet}"


_DDG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


async def web_search(query: str, max_results: int | None = None) -> list[SearchResult]:
    """Run a web search and return parsed results. Raises ``RuntimeError`` on
    network/parse failure so the caller can surface a helpful message."""
    max_results = max_results or settings.WEB_SEARCH_MAX_RESULTS
    provider = (settings.WEB_SEARCH_PROVIDER or "").lower()

    if provider == "tavily" and settings.WEB_SEARCH_API_KEY:
        return await _search_tavily(query, max_results)
    if provider in ("brave", "bravesearch") and settings.WEB_SEARCH_API_KEY:
        return await _search_brave(query, max_results)
    return await _search_duckduckgo(query, max_results)


async def _search_duckduckgo(query: str, max_results: int) -> list[SearchResult]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0)) as client:
            response = await client.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": query, "kl": ""},
                headers=_DDG_HEADERS,
            )
            response.raise_for_status()
            html = response.text
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Web search request failed: {exc}") from exc

    return _parse_duckduckgo(html, max_results)


def _parse_duckduckgo(html: str, max_results: int) -> list[SearchResult]:
    # Each result row: <a class='result-link' href='...'>TITLE</a> followed by
    # a snippet in a class='result-snippet' cell. The class attribute uses
    # single quotes in DuckDuckGo's Lite markup, so match quotes agnostically.
    # Capture the whole anchor tag (attributes + inner text) so we can read the
    # href regardless of whether it appears before or after the class attr.
    anchors = re.findall(r"<a\b[^>]*class=['\"]result-link['\"][^>]*>.*?</a>", html, re.DOTALL)
    parsed: list[tuple[str, str]] = []
    for anchor in anchors:
        m = re.search(r"href=['\"]([^'\"]+)['\"]", anchor)
        if not m:
            continue
        # Inner text is everything between the first > and the closing </a>.
        inner = anchor.split(">", 1)[-1].rsplit("</a>", 1)[0]
        parsed.append((m.group(1), inner))
    results: list[SearchResult] = []
    for href, raw_title in parsed:
        if len(results) >= max_results:
            break
        title = _strip_tags(raw_title).strip()
        title = unescape(title)
        url = _normalize_url(href)
        if not title or not url:
            continue
        snippet = _snippet_after(html, href)
        results.append(SearchResult(title=title, url=url, snippet=snippet))
    if not results:
        raise RuntimeError("Web search returned no results for this query.")
    return results


def _snippet_after(html: str, href: str) -> str:
    idx = html.find(href)
    if idx == -1:
        return ""
    tail = html[idx:]
    # Snippet text usually sits in the next cell after the title link.
    # Match the snippet cell quote-agnostically.
    m = re.search(r"class=['\"]result-snippet['\"][^>]*>(.*?)</td>", tail, re.DOTALL)
    if not m:
        m = re.search(r"class=['\"][^'\"]*snippet[^'\"]*['\"][^>]*>(.*?)</", tail, re.DOTALL)
    if not m:
        m = re.search(r"<td[^>]*>(.*?)</td>", tail, re.DOTALL)
    if not m:
        return ""
    return unescape(_strip_tags(m.group(1)).strip())[:400]


def _normalize_url(href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://duckduckgo.com" + href
    return href


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


async def _search_tavily(query: str, max_results: int) -> list[SearchResult]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0)) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.WEB_SEARCH_API_KEY,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Tavily search request failed: {exc}") from exc

    results: list[SearchResult] = []
    for item in data.get("results", [])[:max_results]:
        url = item.get("url", "")
        if not url:
            continue
        results.append(SearchResult(
            title=item.get("title", url),
            url=url,
            snippet=(item.get("content") or "")[:400],
        ))
    if not results:
        raise RuntimeError("Web search returned no results for this query.")
    return results


async def _search_brave(query: str, max_results: int) -> list[SearchResult]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0)) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": settings.WEB_SEARCH_API_KEY,
                },
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Brave search request failed: {exc}") from exc

    results: list[SearchResult] = []
    for item in data.get("web", {}).get("results", [])[:max_results]:
        url = item.get("url", "")
        if not url:
            continue
        results.append(SearchResult(
            title=item.get("title", url),
            url=url,
            snippet=(item.get("description") or "")[:400],
        ))
    if not results:
        raise RuntimeError("Web search returned no results for this query.")
    return results


def format_context(query: str, results: list[SearchResult]) -> str:
    """Render search results as a system/context block the model can use."""
    if not results:
        return ""
    lines = "\n".join(r.to_context() for r in results)
    return (
        f"Web search results for the user's question ({query}):\n"
        f"{lines}\n\n"
        "Use the sources above to answer when relevant. Cite the source URL "
        "when you base a claim on a search result."
    )
