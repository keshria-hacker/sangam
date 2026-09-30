"""test_websearch — consolidated tests.

Merged from:
- test_websearch.py
- test_websearch_new.py
"""

import os
import sys
from pathlib import Path

# --- Test environment (must run before backend imports) ---------------------
ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "mainfiles")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ["TEST_MODE"] = "1"

from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("MASTER_KEY", Fernet.generate_key().decode())

# --- imports ---
import asyncio

import sys

import unittest

from pathlib import Path

from unittest.mock import patch

import backend.websearch

import os

from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.fernet import Fernet

from backend.websearch import (
    SearchResult,
    _parse_duckduckgo,
    _snippet_after,
    _normalize_url,
    _strip_tags,
    format_context,
    web_search,
)


# --- tests ---

class WebSearchTests(unittest.TestCase):
    def test_format_context_renders_sources(self):
        results = [
            backend.websearch.SearchResult(title="FastAPI", url="https://fastapi.tiangolo.com/", snippet="Web framework."),
        ]
        ctx = backend.websearch.format_context("fastapi", results)
        self.assertIn("https://fastapi.tiangolo.com/", ctx)
        self.assertIn("Web framework.", ctx)

    def test_duckduckgo_parser_extracts_results(self):
        html = """
        <tr><td><a rel="nofollow" href="https://example.com/a" class='result-link'>Example A</a></td></tr>
        <tr><td class='result-snippet'><b>Example A</b> is a test site about things.</td></tr>
        <tr><td><a rel="nofollow" href="https://example.com/b" class='result-link'>Example B</a></td></tr>
        <tr><td class='result-snippet'>Example B covers more topics here.</td></tr>
        """
        results = backend.websearch._parse_duckduckgo(html, 5)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].url, "https://example.com/a")
        self.assertEqual(results[0].title, "Example A")
        self.assertIn("test site", results[0].snippet)

    def test_web_search_raises_on_empty(self):
        html = "<html><body>no results here</body></html>"
        with self.assertRaises(RuntimeError):
            backend.websearch._parse_duckduckgo(html, 5)

    def test_live_web_search_returns_real_results(self):
        # Hits DuckDuckGo Lite for real; proves web search actually works.
        results = asyncio.run(
            backend.websearch.web_search("openai api pricing", max_results=3)
        )
        self.assertGreaterEqual(len(results), 1)
        for r in results:
            self.assertTrue(r.url.startswith("http"))


if __name__ == "__main__":
    unittest.main()


_test_key = Fernet.generate_key().decode()


class SearchResultTests(unittest.TestCase):
    """Tests for SearchResult dataclass."""

    def test_search_result_creation(self):
        """SearchResult creates with all fields."""
        result = SearchResult(
            title="Test Title",
            url="https://example.com",
            snippet="This is a test snippet."
        )
        self.assertEqual(result.title, "Test Title")
        self.assertEqual(result.url, "https://example.com")
        self.assertEqual(result.snippet, "This is a test snippet.")

    def test_to_context_format(self):
        """to_context returns formatted string."""
        result = SearchResult(
            title="Test Title",
            url="https://example.com/page",
            snippet="Test snippet"
        )
        context = result.to_context()
        self.assertIn("Test Title", context)
        self.assertIn("https://example.com/page", context)
        self.assertIn("Test snippet", context)
        self.assertTrue(context.startswith("- "))

    def test_to_context_with_special_chars(self):
        """to_context handles special characters."""
        result = SearchResult(
            title="Title with 'quotes' & <tags>",
            url="https://example.com?q=a&b",
            snippet="Snippet with \"quotes\""
        )
        context = result.to_context()
        self.assertIn("Title with", context)
        self.assertIn("quotes", context)


class ParseDuckDuckGoTests(unittest.TestCase):
    """Tests for _parse_duckduckgo function."""

    def sample_ddg_html(self):
        """Sample DuckDuckGo Lite HTML for testing.

        Note: In actual DDG Lite, the anchor comes BEFORE the snippet cell
        in the HTML structure, so _snippet_after finds the snippet after
        the anchor's href.
        """
        return """
        <table>
            <tr>
                <td><a class='result-link' href='https://example.com/first'>First Result Title</a></td>
                <td class="result-snippet">First result snippet text here.</td>
            </tr>
            <tr>
                <td><a class='result-link' href='https://example.com/second'>Second Result Title</a></td>
                <td class="result-snippet">Second result snippet with details.</td>
            </tr>
            <tr>
                <td><a class='result-link' href='//example.com/third'>Third Result Title</a></td>
                <td class="result-snippet">Third snippet for testing.</td>
            </tr>
        </table>
        """

    def test_parse_basic_results(self):
        """Parse basic DuckDuckGo results."""
        html = self.sample_ddg_html()
        results = _parse_duckduckgo(html, 5)

        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].title, "First Result Title")
        self.assertEqual(results[0].url, "https://example.com/first")
        self.assertIn("First result snippet", results[0].snippet)
        self.assertEqual(results[1].title, "Second Result Title")
        self.assertEqual(results[1].url, "https://example.com/second")
        self.assertEqual(results[2].title, "Third Result Title")
        self.assertEqual(results[2].url, "https://example.com/third")

    def test_parse_respects_max_results(self):
        """Parsing respects max_results limit."""
        html = self.sample_ddg_html()
        results = _parse_duckduckgo(html, 2)
        self.assertEqual(len(results), 2)

    def test_parse_empty_html(self):
        """Empty HTML raises RuntimeError."""
        with self.assertRaises(RuntimeError) as cm:
            _parse_duckduckgo("", 5)
        self.assertIn("no results", str(cm.exception).lower())

    def test_parse_no_matching_anchors(self):
        """HTML without result-link class raises RuntimeError."""
        html = "<table><tr><td>No links here</td></tr></table>"
        with self.assertRaises(RuntimeError) as cm:
            _parse_duckduckgo(html, 5)
        self.assertIn("no results", str(cm.exception).lower())

    def test_parse_double_quotes_in_class(self):
        """Handles double quotes in class attribute."""
        html = """
        <table>
            <tr>
                <td class="result-snippet">Snippet</td>
                <td><a class="result-link" href="https://example.com">Title</a></td>
            </tr>
        </table>
        """
        results = _parse_duckduckgo(html, 5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Title")

    def test_parse_mixed_quotes(self):
        """Handles mixed single/double quotes."""
        html = """
        <table>
            <tr>
                <td class='result-snippet'>Snippet</td>
                <td><a class="result-link" href='https://example.com'>Title</a></td>
            </tr>
        </table>
        """
        results = _parse_duckduckgo(html, 5)
        self.assertEqual(len(results), 1)

    def test_parse_strips_html_from_title(self):
        """HTML tags in title are stripped."""
        html = """
        <table>
            <tr>
                <td class='result-snippet'>Snippet</td>
                <td><a class='result-link' href='https://example.com'>
                    <b>Bold</b> Title with <i>italic</i>
                </a></td>
            </tr>
        </table>
        """
        results = _parse_duckduckgo(html, 5)
        self.assertEqual(results[0].title, "Bold Title with italic")

    def test_parse_unescapes_html_entities(self):
        """HTML entities in title are unescaped."""
        html = """
        <table>
            <tr>
                <td><a class='result-link' href='https://example.com'>
                    Title & "Quotes"
                </a></td>
                <td class='result-snippet'>Snippet</td>
            </tr>
        </table>
        """
        results = _parse_duckduckgo(html, 5)
        # HTML entities should be decoded: & -> &, < -> <, > -> >
        # But bare < > are stripped by _strip_tags as they look like tags
        self.assertIn("&", results[0].title)
        self.assertIn('"', results[0].title)
        self.assertEqual(results[0].title, 'Title & "Quotes"')

    def test_parse_relative_urls(self):
        """Relative URLs are normalized."""
        html = """
        <table>
            <tr>
                <td class='result-snippet'>Snippet</td>
                <td><a class='result-link' href='/relative/path'>Title</a></td>
            </tr>
            <tr>
                <td class='result-snippet'>Snippet</td>
                <td><a class='result-link' href='//domain.com/proto-rel'>Title2</a></td>
            </tr>
        </table>
        """
        results = _parse_duckduckgo(html, 5)
        self.assertEqual(results[0].url, "https://duckduckgo.com/relative/path")
        self.assertEqual(results[1].url, "https://domain.com/proto-rel")

    def test_parse_long_snippet_truncated(self):
        """Long snippets are truncated to 400 chars."""
        long_snippet = "x" * 500
        html = f"""
        <table>
            <tr>
                <td class='result-snippet'>{long_snippet}</td>
                <td><a class='result-link' href='https://example.com'>Title</a></td>
            </tr>
        </table>
        """
        results = _parse_duckduckgo(html, 5)
        self.assertLessEqual(len(results[0].snippet), 400)

    def test_parse_missing_snippet_handled(self):
        """Missing snippet cell returns empty string."""
        html = """
        <table>
            <tr>
                <td><a class='result-link' href='https://example.com'>Title</a></td>
            </tr>
        </table>
        """
        results = _parse_duckduckgo(html, 5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].snippet, "")


class SnippetAfterTests(unittest.TestCase):
    """Tests for _snippet_after function."""

    def test_snippet_after_basic(self):
        """Extracts snippet after href."""
        html = "<a href='https://example.com'>Title</a><td class='result-snippet'>The snippet</td>"
        result = _snippet_after(html, "https://example.com")
        self.assertEqual(result, "The snippet")

    def test_snippet_not_found(self):
        """Returns empty string when href not found."""
        result = _snippet_after("no link here", "https://example.com")
        self.assertEqual(result, "")

    def test_snippet_handles_different_patterns(self):
        """Tries multiple regex patterns for snippet."""
        # Try without result-snippet class
        html = "<a href='https://example.com'>Title</a><td class='other'>Snippet text</td>"
        result = _snippet_after(html, "https://example.com")
        self.assertEqual(result, "Snippet text")

    def test_snippet_unescapes(self):
        """HTML entities in snippet are unescaped."""
        html = "<a href='https://example.com'>Title</a><td class='result-snippet'>A & B</td>"
        result = _snippet_after(html, "https://example.com")
        self.assertEqual(result, "A & B")

    def test_snippet_strips_tags(self):
        """HTML tags in snippet are stripped."""
        html = "<a href='https://example.com'>Title</a><td class='result-snippet'><b>Bold</b> text</td>"
        result = _snippet_after(html, "https://example.com")
        self.assertEqual(result, "Bold text")


class NormalizeUrlTests(unittest.TestCase):
    """Tests for _normalize_url function."""

    def test_absolute_url_unchanged(self):
        """Absolute URLs passed through."""
        self.assertEqual(_normalize_url("https://example.com/path"), "https://example.com/path")
        self.assertEqual(_normalize_url("http://example.com"), "http://example.com")

    def test_protocol_relative_url(self):
        """Protocol-relative URLs get https: prefix."""
        self.assertEqual(_normalize_url("//example.com/path"), "https://example.com/path")

    def test_relative_url(self):
        """Relative URLs get duckduckgo base."""
        self.assertEqual(_normalize_url("/path"), "https://duckduckgo.com/path")

    def test_empty_string(self):
        """Empty string returns empty string."""
        self.assertEqual(_normalize_url(""), "")


class StripTagsTests(unittest.TestCase):
    """Tests for _strip_tags function."""

    def test_basic_stripping(self):
        """HTML tags removed."""
        self.assertEqual(_strip_tags("<b>hello</b>"), "hello")
        self.assertEqual(_strip_tags("<i>italic</i> text"), "italic text")

    def test_nested_tags(self):
        """Nested tags stripped."""
        self.assertEqual(_strip_tags("<div><span>text</span></div>"), "text")

    def test_self_closing_tags(self):
        """Self-closing tags removed."""
        self.assertEqual(_strip_tags("before<br/>after"), "beforeafter")
        self.assertEqual(_strip_tags("before<hr>after"), "beforeafter")

    def test_no_tags(self):
        """Text without tags unchanged."""
        self.assertEqual(_strip_tags("plain text"), "plain text")

    def test_empty_string(self):
        """Empty string returns empty."""
        self.assertEqual(_strip_tags(""), "")

    def test_malformed_tags(self):
        """Malformed tags handled gracefully."""
        # The regex <[^>]+> matches any <...> sequence
        self.assertEqual(_strip_tags("<unclosed"), "<unclosed")
        self.assertEqual(_strip_tags("unclosed>"), "unclosed>")


class FormatContextTests(unittest.TestCase):
    """Tests for format_context function."""

    def test_empty_results(self):
        """Empty results returns empty string."""
        result = format_context("query", [])
        self.assertEqual(result, "")

    def test_single_result(self):
        """Single result formatted correctly."""
        results = [SearchResult("Title", "https://example.com", "Snippet")]
        context = format_context("test query", results)

        self.assertIn("Web search results for the user's question (test query):", context)
        self.assertIn("- Title (https://example.com): Snippet", context)
        self.assertIn("Use the sources above to answer", context)

    def test_multiple_results(self):
        """Multiple results all included."""
        results = [
            SearchResult("Title 1", "https://example.com/1", "Snippet 1"),
            SearchResult("Title 2", "https://example.com/2", "Snippet 2"),
            SearchResult("Title 3", "https://example.com/3", "Snippet 3"),
        ]
        context = format_context("multi query", results)

        self.assertIn("Title 1", context)
        self.assertIn("Title 2", context)
        self.assertIn("Title 3", context)
        self.assertIn("https://example.com/1", context)
        self.assertIn("https://example.com/2", context)
        self.assertIn("https://example.com/3", context)

    def test_special_chars_in_query(self):
        """Query with special characters included in header."""
        results = [SearchResult("T", "https://e.com", "S")]
        context = format_context("query with 'quotes' & <tags>", results)
        self.assertIn("query with 'quotes' & <tags>", context)

    def test_result_to_context_called(self):
        """Each result's to_context is used."""
        results = [SearchResult("T", "https://e.com", "S")]
        context = format_context("q", results)
        # to_context format: "- Title (url): snippet"
        self.assertIn("- T (https://e.com): S", context)


class WebSearchTestsNew(unittest.IsolatedAsyncioTestCase):
    """Tests for web_search function (mocked)."""

    async def test_duckduckgo_search_called(self):
        """web_search calls DuckDuckGo when provider not set."""
        with patch("backend.websearch._search_duckduckgo", new_callable=AsyncMock) as mock_ddg:
            mock_ddg.return_value = [SearchResult("T", "https://e.com", "S")]

            results = await web_search("test query", 3)

            mock_ddg.assert_called_once_with("test query", 3)
            self.assertEqual(len(results), 1)

    async def test_duckduckgo_default_max_results(self):
        """Default max_results from settings used."""
        with patch("backend.websearch._search_duckduckgo", new_callable=AsyncMock) as mock_ddg:
            mock_ddg.return_value = [SearchResult("T", "https://e.com", "S")]
            # Import settings to check default
            from backend.config import settings
            defaults = settings.WEB_SEARCH_MAX_RESULTS

            await web_search("query", None)

            mock_ddg.assert_called_once_with("query", defaults)

    async def test_tavily_search_when_configured(self):
        """Tavily used when provider=tavily and key set."""
        with patch("backend.websearch.settings") as mock_settings:
            mock_settings.WEB_SEARCH_PROVIDER = "tavily"
            mock_settings.WEB_SEARCH_API_KEY = "test-key"
            mock_settings.WEB_SEARCH_MAX_RESULTS = 5

            with patch("backend.websearch._search_tavily", new_callable=AsyncMock) as mock_tavily:
                mock_tavily.return_value = [SearchResult("T", "https://e.com", "S")]

                results = await web_search("query", 3)

                mock_tavily.assert_called_once_with("query", 3)

    async def test_brave_search_when_configured(self):
        """Brave used when provider=brave and key set."""
        with patch("backend.websearch.settings") as mock_settings:
            mock_settings.WEB_SEARCH_PROVIDER = "brave"
            mock_settings.WEB_SEARCH_API_KEY = "test-key"
            mock_settings.WEB_SEARCH_MAX_RESULTS = 5

            with patch("backend.websearch._search_brave", new_callable=AsyncMock) as mock_brave:
                mock_brave.return_value = [SearchResult("T", "https://e.com", "S")]

                results = await web_search("query", 3)

                mock_brave.assert_called_once_with("query", 3)

    async def test_bravesearch_alias(self):
        """bravesearch alias works."""
        with patch("backend.websearch.settings") as mock_settings:
            mock_settings.WEB_SEARCH_PROVIDER = "bravesearch"
            mock_settings.WEB_SEARCH_API_KEY = "test-key"

            with patch("backend.websearch._search_brave", new_callable=AsyncMock) as mock_brave:
                mock_brave.return_value = [SearchResult("T", "https://e.com", "S")]

                await web_search("query", 3)
                mock_brave.assert_called_once()

    async def test_fallback_to_duckduckgo_no_key(self):
        """Falls back to DuckDuckGo if provider set but no API key."""
        with patch("backend.websearch.settings") as mock_settings:
            mock_settings.WEB_SEARCH_PROVIDER = "tavily"
            mock_settings.WEB_SEARCH_API_KEY = None  # No key

            with patch("backend.websearch._search_duckduckgo", new_callable=AsyncMock) as mock_ddg:
                mock_ddg.return_value = [SearchResult("T", "https://e.com", "S")]

                await web_search("query", 3)
                mock_ddg.assert_called_once()


class SearchTavilyTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _search_tavily function (mocked HTTP)."""

    @patch("backend.websearch.settings")
    async def test_successful_response(self, mock_settings):
        """Successful Tavily response parsed correctly."""
        mock_settings.WEB_SEARCH_API_KEY = "test-key"

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"title": "Result 1", "url": "https://example.com/1", "content": "Content 1"},
                {"title": "Result 2", "url": "https://example.com/2", "content": "Content 2"},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            from backend.websearch import _search_tavily
            results = await _search_tavily("query", 5)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].title, "Result 1")
            self.assertEqual(results[0].url, "https://example.com/1")
            self.assertEqual(results[0].snippet, "Content 1")

    @patch("backend.websearch.settings")
    async def test_empty_results_raises(self, mock_settings):
        """Empty results raises RuntimeError."""
        mock_settings.WEB_SEARCH_API_KEY = "test-key"

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"results": []}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            from backend.websearch import _search_tavily
            with self.assertRaises(RuntimeError) as cm:
                await _search_tavily("query", 5)
            self.assertIn("no results", str(cm.exception).lower())

    @patch("backend.websearch.settings")
    async def test_missing_url_skipped(self, mock_settings):
        """Results without URL are skipped."""
        mock_settings.WEB_SEARCH_API_KEY = "test-key"

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"title": "No URL", "content": "Content"},
                {"title": "Has URL", "url": "https://example.com", "content": "Content"},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            from backend.websearch import _search_tavily
            results = await _search_tavily("query", 5)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].title, "Has URL")

    @patch("backend.websearch.settings")
    async def test_snippet_truncated(self, mock_settings):
        """Long snippets truncated to 400 chars."""
        mock_settings.WEB_SEARCH_API_KEY = "test-key"
        long_content = "x" * 500

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "results": [{"title": "T", "url": "https://e.com", "content": long_content}]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            from backend.websearch import _search_tavily
            results = await _search_tavily("query", 5)

            self.assertEqual(len(results[0].snippet), 400)

    @patch("backend.websearch.settings")
    async def test_http_error_raises(self, mock_settings):
        """HTTP errors raise RuntimeError."""
        mock_settings.WEB_SEARCH_API_KEY = "test-key"

        import httpx
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.side_effect = httpx.HTTPError("Connection failed")
            mock_client_class.return_value = mock_client

            from backend.websearch import _search_tavily
            with self.assertRaises(RuntimeError) as cm:
                await _search_tavily("query", 5)
            self.assertIn("tavily search request failed", str(cm.exception).lower())


class SearchBraveTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _search_brave function (mocked HTTP)."""

    @patch("backend.websearch.settings")
    async def test_successful_response(self, mock_settings):
        """Successful Brave response parsed correctly."""
        mock_settings.WEB_SEARCH_API_KEY = "test-key"

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "web": {
                "results": [
                    {"title": "Result 1", "url": "https://example.com/1", "description": "Desc 1"},
                    {"title": "Result 2", "url": "https://example.com/2", "description": "Desc 2"},
                ]
            }
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            from backend.websearch import _search_brave
            results = await _search_brave("query", 5)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].title, "Result 1")
            self.assertEqual(results[0].url, "https://example.com/1")
            self.assertEqual(results[0].snippet, "Desc 1")

    @patch("backend.websearch.settings")
    async def test_empty_web_results_raises(self, mock_settings):
        """Empty web results raises RuntimeError."""
        mock_settings.WEB_SEARCH_API_KEY = "test-key"

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"web": {"results": []}}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            from backend.websearch import _search_brave
            with self.assertRaises(RuntimeError) as cm:
                await _search_brave("query", 5)
            self.assertIn("no results", str(cm.exception).lower())

    @patch("backend.websearch.settings")
    async def test_missing_web_key_handled(self, mock_settings):
        """Missing 'web' key handled gracefully."""
        mock_settings.WEB_SEARCH_API_KEY = "test-key"

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {}  # No 'web' key

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            from backend.websearch import _search_brave
            with self.assertRaises(RuntimeError) as cm:
                await _search_brave("query", 5)
            self.assertIn("no results", str(cm.exception).lower())

    @patch("backend.websearch.settings")
    async def test_missing_url_skipped(self, mock_settings):
        """Results without URL skipped."""
        mock_settings.WEB_SEARCH_API_KEY = "test-key"

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "web": {
                "results": [
                    {"title": "No URL", "description": "Desc"},
                    {"title": "Has URL", "url": "https://example.com", "description": "Desc"},
                ]
            }
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            from backend.websearch import _search_brave
            results = await _search_brave("query", 5)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].title, "Has URL")

    @patch("backend.websearch.settings")
    async def test_snippet_truncated(self, mock_settings):
        """Long description truncated to 400 chars."""
        mock_settings.WEB_SEARCH_API_KEY = "test-key"
        long_desc = "x" * 500

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "web": {"results": [{"title": "T", "url": "https://e.com", "description": long_desc}]}
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            from backend.websearch import _search_brave
            results = await _search_brave("query", 5)

            self.assertEqual(len(results[0].snippet), 400)

    @patch("backend.websearch.settings")
    async def test_http_error_raises(self, mock_settings):
        """HTTP errors raise RuntimeError."""
        mock_settings.WEB_SEARCH_API_KEY = "test-key"

        import httpx
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.side_effect = httpx.HTTPError("Connection failed")
            mock_client_class.return_value = mock_client

            from backend.websearch import _search_brave
            with self.assertRaises(RuntimeError) as cm:
                await _search_brave("query", 5)
            self.assertIn("brave search request failed", str(cm.exception).lower())


class DuckDuckGoSearchTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _search_duckduckgo function (mocked HTTP)."""

    @patch("backend.websearch._parse_duckduckgo")
    @patch("httpx.AsyncClient")
    async def test_successful_request(self, mock_client_class, mock_parse):
        """Successful DDG request returns parsed results."""
        mock_parse.return_value = [SearchResult("T", "https://e.com", "S")]

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.text = "<html>results</html>"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        from backend.websearch import _search_duckduckgo
        results = await _search_duckduckgo("query", 5)

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        self.assertEqual(call_args[0][0], "https://lite.duckduckgo.com/lite/")
        self.assertEqual(call_args[1]["data"]["q"], "query")
        self.assertEqual(len(results), 1)

    @patch("httpx.AsyncClient")
    async def test_http_error_raises(self, mock_client_class):
        """HTTP errors raise RuntimeError."""
        import httpx

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.side_effect = httpx.HTTPError("Connection failed")
        mock_client_class.return_value = mock_client

        from backend.websearch import _search_duckduckgo
        with self.assertRaises(RuntimeError) as cm:
            await _search_duckduckgo("query", 5)
        self.assertIn("web search request failed", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main()
