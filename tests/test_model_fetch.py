"""
Tests for ``fetch_models_from_provider()`` — the public, standalone
function that queries any provider's model listing API and returns a
standardised list of dicts.  Also covers the refactored private wrapper
``_fetch_provider_models()`` that delegates to it.

All HTTP calls are fully mocked — no real network requests.
"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mainfiles"))

from mainfiles.backend import llm


# ---------------------------------------------------------------------------
# Mock helpers — reusable fake HTTP client/responses shared across tests.
# ---------------------------------------------------------------------------

class FakeResponse:
    """Simulates ``httpx.Response`` for our mocked ``AsyncClient.get()``."""
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code} error",
                request=None,
                response=self,
            )

    def json(self):
        return self._json_data


class FakeClient:
    """Simulates ``httpx.AsyncClient``.  Each test provides a ``responses``
    callable that receives the request URL and returns a ``FakeResponse``."""
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args, **kwargs):
        return False

    async def get(self, url, **kwargs):
        return self._handler(url, **kwargs)  # type: ignore[attr-defined]


def _make_client(handler):
    """Patch ``httpx.AsyncClient`` so every instance uses *handler* (a
    callable ``(url, **kwargs) -> FakeResponse``)."""
    return patch.object(
        httpx,
        "AsyncClient",
        lambda *a, **kw: type("FakeClient", (FakeClient,), {"_handler": staticmethod(handler)})(),
    )


# ---------------------------------------------------------------------------
# Tests for `fetch_models_from_provider()`
# ---------------------------------------------------------------------------

class FetchModelsFromProviderTests(unittest.TestCase):
    """Every auth scheme, pagination, filtering, and error path."""

    # -- happy paths -------------------------------------------------------

    def test_bearer_auth(self):
        """Bearer token auth (OpenAI, Together, Groq, OpenRouter, …)."""
        def handler(url, **kw):
            self.assertIn("Authorization", kw.get("headers", {}))
            self.assertEqual(kw["headers"]["Authorization"], "Bearer sk-test")
            return FakeResponse({"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]})

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="sk-test",
                endpoint_url="https://api.openai.com/v1/models",
                provider_id="openai",
                provider_label="OpenAI",
                auth_type="bearer",
            ))

        self.assertEqual(len(models), 2)
        self.assertEqual(models[0]["id"], "gpt-4o")
        self.assertEqual(models[0]["provider"], "openai")
        self.assertEqual(models[0]["provider_label"], "OpenAI")
        self.assertEqual(models[0]["description"], "")
        self.assertEqual(models[1]["id"], "gpt-4o-mini")

    def test_header_auth(self):
        """Custom header auth (Anthropic-style X-API-Key)."""
        def handler(url, **kw):
            self.assertEqual(kw["headers"].get("x-api-key"), "sk-ant-test")
            self.assertEqual(kw["headers"].get("anthropic-version"), "2023-06-01")
            return FakeResponse({"data": [{"id": "claude-sonnet-5"}]})

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="sk-ant-test",
                endpoint_url="https://api.anthropic.com/v1/models",
                provider_id="anthropic",
                provider_label="Anthropic",
                auth_type="header",
                auth_header_name="x-api-key",
                extra_headers={"anthropic-version": "2023-06-01"},
            ))

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["id"], "claude-sonnet-5")
        self.assertEqual(models[0]["provider"], "anthropic")

    def test_query_auth(self):
        """Query-parameter auth (Gemini-style ``?key=...``)."""
        def handler(url, **kw):
            self.assertIn("key=AIza-test", url)
            return FakeResponse({"models": [{"name": "models/gemini-2.5-pro"}]})

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="AIza-test",
                endpoint_url="https://generativelanguage.googleapis.com/v1beta/models",
                provider_id="gemini",
                provider_label="Gemini",
                auth_type="query",
                query_key="key",
                json_path="models",
                id_field="name",
                strip_prefix="models/",
            ))

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["id"], "gemini-2.5-pro")

    # -- name / description fields -----------------------------------------

    def test_name_field(self):
        """When a custom ``name_field`` is provided, it should be used."""
        def handler(url, **kw):
            return FakeResponse({"data": [
                {"id": "gpt-4o", "display_name": "GPT-4 Omni"},
            ]})

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="sk-test",
                endpoint_url="https://api.openai.com/v1/models",
                provider_id="openai",
                provider_label="OpenAI",
                name_field="display_name",
            ))

        self.assertEqual(models[0]["name"], "GPT-4 Omni")

    def test_name_field_falls_back_to_readable_name(self):
        """When ``name_field`` is set but missing in the entry, derive from id."""
        def handler(url, **kw):
            return FakeResponse({"data": [{"id": "nvidia/meta/llama-3.3-70b-instruct"}]})

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="key",
                endpoint_url="https://integrate.api.nvidia.com/v1/models",
                provider_id="nvidia",
                provider_label="NVIDIA NIM",
                name_field="display_name",  # not present in the entry
            ))

        # Falls back to last segment after "/"
        self.assertEqual(models[0]["name"], "llama-3.3-70b-instruct")

    def test_description_field(self):
        """Description is extracted when ``description_field`` is specified."""
        def handler(url, **kw):
            return FakeResponse({"data": [
                {"id": "gpt-4o", "description": "The latest multimodal model"},
            ]})

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="sk-test",
                endpoint_url="https://api.openai.com/v1/models",
                provider_id="openai",
                provider_label="OpenAI",
                description_field="description",
            ))

        self.assertEqual(models[0]["description"], "The latest multimodal model")

    def test_description_field_missing(self):
        """When ``description_field`` is set but missing, description is empty."""
        def handler(url, **kw):
            return FakeResponse({"data": [{"id": "gpt-4o"}]})

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="sk-test",
                endpoint_url="https://api.openai.com/v1/models",
                provider_id="openai",
                provider_label="OpenAI",
                description_field="description",
            ))

        self.assertEqual(models[0]["description"], "")

    # -- strip_prefix ------------------------------------------------------

    def test_strip_prefix(self):
        """Model IDs have a prefix stripped (Gemini ``models/`` -> ``gemini-...``)."""
        def handler(url, **kw):
            return FakeResponse({"models": [
                {"name": "models/gemini-2.5-pro"},
                {"name": "models/gemini-1.5-flash"},
            ]})

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="AIza-test",
                endpoint_url="https://generativelanguage.googleapis.com/v1beta/models",
                provider_id="gemini",
                provider_label="Gemini",
                auth_type="query",
                query_key="key",
                json_path="models",
                id_field="name",
                strip_prefix="models/",
            ))

        ids = [m["id"] for m in models]
        self.assertIn("gemini-2.5-pro", ids)
        self.assertIn("gemini-1.5-flash", ids)
        # No model id should still have the prefix
        self.assertFalse(any("models/" in mid for mid in ids))

    # -- pagination --------------------------------------------------------

    def test_pagination_follows_next_links(self):
        """When the API returns a ``next`` field, the function follows it
        and consumes every page."""
        pages = iter([
            FakeResponse({
                "data": [{"id": "page1-model-a"}, {"id": "page1-model-b"}],
                "next": "https://api.example.com/v1/models?page=2",
            }),
            FakeResponse({
                "data": [{"id": "page2-model-c"}],
                "next": "https://api.example.com/v1/models?page=3",
            }),
            FakeResponse({
                "data": [{"id": "page3-model-d"}, {"id": "page3-model-e"}],
                "next": None,
            }),
        ])

        def handler(url, **kw):
            return next(pages)

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="sk-test",
                endpoint_url="https://api.example.com/v1/models",
                provider_id="example",
                provider_label="Example",
            ))

        ids = [m["id"] for m in models]
        self.assertEqual(ids, [
            "page1-model-a", "page1-model-b",
            "page2-model-c",
            "page3-model-d", "page3-model-e",
        ])

    def test_pagination_avoids_infinite_loop_on_self_referencing_next(self):
        """A ``next`` URL that points back to a visited page must not loop."""
        pages = iter([
            FakeResponse({
                "data": [{"id": "a"}],
                "next": "https://api.example.com/v1/models",
            }),
        ])

        def handler(url, **kw):
            return next(pages)

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="sk-test",
                endpoint_url="https://api.example.com/v1/models",
                provider_id="example",
                provider_label="Example",
            ))

        self.assertEqual([m["id"] for m in models], ["a"])

    # -- non-chat filtering ------------------------------------------------

    def test_filters_out_non_chat_models(self):
        """Models whose id contains an ``_NON_CHAT_MARKERS`` substring
        (embed, rerank, tts, whisper, dall-e, moderation) are dropped."""
        def handler(url, **kw):
            return FakeResponse({"data": [
                {"id": "gpt-4o"},
                {"id": "text-embedding-ada-002"},      # "embed" -> drop
                {"id": "dall-e-3"},                     # "dall-e" -> drop
                {"id": "whisper-1"},                    # "whisper" -> drop
                {"id": "tts-1"},                        # "tts" -> drop
                {"id": "gpt-4o-mini"},
                {"id": "rerank-model-v2"},              # "rerank" -> drop
            ]})

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="sk-test",
                endpoint_url="https://api.openai.com/v1/models",
                provider_id="openai",
                provider_label="OpenAI",
            ))

        ids = [m["id"] for m in models]
        self.assertIn("gpt-4o", ids)
        self.assertIn("gpt-4o-mini", ids)
        self.assertNotIn("text-embedding-ada-002", ids)
        self.assertNotIn("dall-e-3", ids)
        self.assertNotIn("whisper-1", ids)
        self.assertNotIn("tts-1", ids)
        self.assertNotIn("rerank-model-v2", ids)

    def test_keeps_vision_and_other_valid_chat_models(self):
        """Models like ``llama-3.2-90b-vision-instruct`` and
        ``cosmos3-nano-reasoner`` must NOT be filtered out."""
        def handler(url, **kw):
            return FakeResponse({"data": [
                {"id": "meta/llama-3.2-90b-vision-instruct"},
                {"id": "nvidia/cosmos3-nano-reasoner"},
                {"id": "nvidia/nemotron-ocr-v2"},
                {"id": "qwen/qwen-image"},
            ]})

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="key",
                endpoint_url="https://integrate.api.nvidia.com/v1/models",
                provider_id="nvidia",
                provider_label="NVIDIA NIM",
            ))

        ids = [m["id"] for m in models]
        self.assertIn("meta/llama-3.2-90b-vision-instruct", ids)
        self.assertIn("nvidia/cosmos3-nano-reasoner", ids)
        self.assertIn("nvidia/nemotron-ocr-v2", ids)
        self.assertIn("qwen/qwen-image", ids)

    # -- deduplication -----------------------------------------------------

    def test_deduplicates_duplicate_ids(self):
        """Duplicate model IDs in the same page or across pages are
        collapsed to a single entry."""
        def handler(url, **kw):
            return FakeResponse({"data": [
                {"id": "gpt-4o"},
                {"id": "gpt-4o"},         # duplicate
                {"id": "gpt-4o-mini"},
                {"id": "gpt-4o"},         # another duplicate
            ]})

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="sk-test",
                endpoint_url="https://api.openai.com/v1/models",
                provider_id="openai",
                provider_label="OpenAI",
            ))

        self.assertEqual(len(models), 2)
        self.assertEqual(models[0]["id"], "gpt-4o")
        self.assertEqual(models[1]["id"], "gpt-4o-mini")

    # -- error / edge cases -------------------------------------------------

    def test_empty_api_key_returns_empty_list(self):
        """An empty or missing API key should short-circuit to []."""
        models = asyncio.run(llm.fetch_models_from_provider(
            api_key="",
            endpoint_url="https://api.openai.com/v1/models",
            provider_id="openai",
            provider_label="OpenAI",
        ))
        self.assertEqual(models, [])

    def test_empty_endpoint_url_returns_empty_list(self):
        """An empty endpoint should short-circuit to []."""
        models = asyncio.run(llm.fetch_models_from_provider(
            api_key="sk-test",
            endpoint_url="",
            provider_id="openai",
            provider_label="OpenAI",
        ))
        self.assertEqual(models, [])

    def test_connection_error_returns_empty_list(self):
        """A network connectivity error is caught and an empty list returned."""
        def handler(url, **kw):
            raise httpx.ConnectError("connection refused")

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="sk-test",
                endpoint_url="https://api.openai.com/v1/models",
                provider_id="openai",
                provider_label="OpenAI",
            ))
        self.assertEqual(models, [])

    def test_timeout_returns_empty_list(self):
        """A timeout error is caught and an empty list returned."""
        def handler(url, **kw):
            raise httpx.TimeoutException("timed out")

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="sk-test",
                endpoint_url="https://api.openai.com/v1/models",
                provider_id="openai",
                provider_label="OpenAI",
            ))
        self.assertEqual(models, [])

    def test_http_404_returns_partial_results(self):
        """If models were collected before a 404, they are returned."""
        def handler(url, **kw):
            if "page=2" in url:
                raise httpx.HTTPStatusError("404", request=None, response=FakeResponse({}, 404))
            return FakeResponse({"data": [{"id": "model-a"}], "next": "https://api.example.com/v1/models?page=2"})

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="sk-test",
                endpoint_url="https://api.example.com/v1/models",
                provider_id="example",
                provider_label="Example",
                timeout_seconds=5.0,
            ))
        # Should have the models from page 1 even though page 2 failed.
        self.assertEqual([m["id"] for m in models], ["model-a"])

    def test_non_dict_entry_is_skipped(self):
        """String or other non-dict entries in the model array are skipped."""
        def handler(url, **kw):
            return FakeResponse({"data": [
                {"id": "valid-model"},
                "string-entry",
                42,
                None,
            ]})

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="sk-test",
                endpoint_url="https://api.example.com/v1/models",
                provider_id="example",
                provider_label="Example",
            ))

        self.assertEqual([m["id"] for m in models], ["valid-model"])

    def test_provider_label_is_set_correctly(self):
        """The ``provider_label`` field must match what was passed in."""
        def handler(url, **kw):
            return FakeResponse({"data": [{"id": "gpt-4o"}]})

        with _make_client(handler):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="sk-test",
                endpoint_url="https://api.openai.com/v1/models",
                provider_id="openai",
                provider_label="OpenAI",
            ))
        self.assertEqual(models[0]["provider_label"], "OpenAI")
        self.assertEqual(models[0]["provider"], "openai")


# ---------------------------------------------------------------------------
# Tests for the refactored ``_fetch_provider_models()`` wrapper
# ---------------------------------------------------------------------------

class FetchProviderModelsWrapperTests(unittest.TestCase):
    """The private wrapper that maps ``PROVIDER_MODEL_API`` config to
    ``fetch_models_from_provider()`` must still produce correct LiteLLM IDs."""

    def test_returns_openai_with_prefix(self):
        def handler(url, **kw):
            return FakeResponse({"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]})

        with _make_client(handler):
            ids = asyncio.run(llm._fetch_provider_models("openai", "sk-test"))

        self.assertEqual(ids, ["openai/gpt-4o", "openai/gpt-4o-mini"])

    def test_returns_gemini_with_prefix(self):
        def handler(url, **kw):
            return FakeResponse({"models": [
                {"name": "models/gemini-1.5-pro"},
                {"name": "models/gemini-embedding-001"},
            ]})

        with _make_client(handler):
            ids = asyncio.run(llm._fetch_provider_models("gemini", "key"))

        self.assertEqual(ids, ["gemini/gemini-1.5-pro"])

    def test_returns_nvidia_with_prefix(self):
        def handler(url, **kw):
            return FakeResponse({"data": [
                {"id": "meta/llama-3.3-70b-instruct"},
                {"id": "nvidia/embed-qa-4"},
                {"id": "nvidia/llama-3.1-nemotron-nano-8b-v1"},
            ]})

        with _make_client(handler):
            ids = asyncio.run(llm._fetch_provider_models("nvidia", "key"))

        self.assertIn("nvidia_nim/meta/llama-3.3-70b-instruct", ids)
        self.assertIn("nvidia_nim/nvidia/llama-3.1-nemotron-nano-8b-v1", ids)
        self.assertNotIn("nvidia_nim/nvidia/embed-qa-4", ids)

    def test_returns_empty_without_key(self):
        ids = asyncio.run(llm._fetch_provider_models("openai", ""))
        self.assertEqual(ids, [])

    def test_returns_empty_for_unknown_provider(self):
        ids = asyncio.run(llm._fetch_provider_models("not-a-provider", "key"))
        self.assertEqual(ids, [])

    def test_deduplicates_prefixed_ids(self):
        """If two raw IDs produce the same prefixed LiteLLM ID, dedup."""
        def handler(url, **kw):
            return FakeResponse({"data": [
                {"id": "gpt-4o"},
                {"id": "openai/gpt-4o"},   # same after prefix: openai/gpt-4o
            ]})

        with _make_client(handler):
            ids = asyncio.run(llm._fetch_provider_models("openai", "sk-test"))

        self.assertEqual(ids, ["openai/gpt-4o"])


class ModelDiscoveryLoggingTests(unittest.TestCase):
    """Silent failures in model discovery must now be logged.

    The graceful-degradation return contracts ([] / partial results) are
    preserved — the audit finding (C-006) is about *visibility*, not raising.
    """

    def test_fetch_models_logs_connection_error(self):
        """A connection error is logged with provider context and returns []."""
        def handler(url, **kw):
            raise httpx.ConnectError("connection refused")

        with (
            _make_client(handler),
            patch("backend.providers.model_discovery.logger") as mock_logger,
        ):
            models = asyncio.run(llm.fetch_models_from_provider(
                api_key="sk-test",
                endpoint_url="https://api.openai.com/v1/models",
                provider_id="openai",
                provider_label="OpenAI",
            ))

        self.assertEqual(models, [])  # contract preserved
        mock_logger.warning.assert_called_once()
        logged = " ".join(str(a) for a in mock_logger.warning.call_args.args)
        self.assertIn("openai", logged)  # provider context logged

    def test_fetch_ollama_logs_unreachable_and_returns_empty(self):
        """Ollama unreachable after retries logs a warning and returns []."""
        def handler(url, **kw):
            raise httpx.ConnectError("connection refused")

        from backend.providers.model_discovery import fetch_ollama_models

        with (
            _make_client(handler),
            patch("backend.providers.ollama._try_start_ollama", new_callable=AsyncMock),
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("backend.providers.model_discovery.logger") as mock_logger,
        ):
            models = asyncio.run(fetch_ollama_models(
                base_url="http://127.0.0.1:11434"
            ))

        self.assertEqual(models, [])  # contract preserved
        mock_logger.warning.assert_called_once()
        logged = " ".join(str(a) for a in mock_logger.warning.call_args.args)
        self.assertIn("Ollama unreachable", logged)


if __name__ == "__main__":
    unittest.main()
