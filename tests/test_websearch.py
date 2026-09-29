import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mainfiles"))

import backend.websearch


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
