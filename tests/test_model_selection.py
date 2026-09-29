import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mainfiles"))

from backend import llm


class ModelSelectionTests(unittest.TestCase):
    def test_live_fetch_returns_exactly_what_provider_api_exposes(self):
        """The picker must mirror the provider's API, not a static catalogue."""
        import httpx

        class FakeResp:
            def __init__(self, data):
                self._data = data
            def raise_for_status(self):
                pass
            def json(self):
                return self._data

        class FakeClient:
            def __init__(self, *a, **k):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def get(self, url, headers=None):
                if "openai.com" in url:
                    # Include a non-chat model to prove filtering happens.
                    return FakeResp({"data": [{"id": "gpt-4o"}, {"id": "dall-e-3"}, {"id": "gpt-4o-mini"}]})
                if "googleapis.com" in url:
                    return FakeResp({"models": [{"name": "models/gemini-1.5-pro"}, {"name": "models/gemini-embedding-001"}]})
                return FakeResp({"data": []})

        with patch.object(httpx, "AsyncClient", lambda *a, **k: FakeClient()):
            openai_ids = asyncio.run(llm._fetch_provider_models("openai", "sk-x"))
            gemini_ids = asyncio.run(llm._fetch_provider_models("gemini", "key"))

        # Only chat-capable models, correct LiteLLM prefixes, no "random" ids.
        self.assertEqual(openai_ids, ["openai/gpt-4o", "openai/gpt-4o-mini"])
        self.assertEqual(gemini_ids, ["gemini/gemini-1.5-pro"])

    def test_nvidia_keeps_chat_models_and_drops_non_chat(self):
        """NVIDIA NIM exposes vision/guard/embedding/rerank models too. The
        picker must keep all chat-capable models (instruct AND others like the
        nemotron-nano chat model) but drop non-chat ones (embedding/guard)."""
        import httpx

        class FakeResp:
            def __init__(self, data):
                self._data = data
            def raise_for_status(self):
                pass
            def json(self):
                return self._data

        class FakeClient:
            def __init__(self, *a, **k):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def get(self, url, headers=None):
                return FakeResp({"data": [
                    {"id": "meta/llama-3.3-70b-instruct"},
                    {"id": "nvidia/llama-3.1-nemotron-nano-8b-v1"},   # chat model, no -instruct
                    {"id": "nvidia/embed-qa-4"},                      # embedding -> drop
                    {"id": "nvidia/llama-3.1-nemotron-70b-instruct"},
                ]})

        with patch.object(httpx, "AsyncClient", lambda *a, **k: FakeClient()):
            ids = asyncio.run(llm._fetch_provider_models("nvidia", "key"))

        self.assertIn("nvidia_nim/meta/llama-3.3-70b-instruct", ids)
        self.assertIn("nvidia_nim/nvidia/llama-3.1-nemotron-nano-8b-v1", ids)
        self.assertIn("nvidia_nim/nvidia/llama-3.1-nemotron-70b-instruct", ids)
        self.assertNotIn("nvidia_nim/nvidia/embed-qa-4", ids)

    def test_live_fetch_returns_empty_without_key(self):
        self.assertEqual(asyncio.run(llm._fetch_provider_models("openai", "")), [])

    def test_models_prefers_live_fetch_over_currated_fallback(self):
        """When the live API answers, curated defaults must not be injected."""
        import httpx

        class FakeResp:
            def __init__(self, data):
                self._data = data
            def raise_for_status(self):
                pass
            def json(self):
                return self._data

        class FakeClient:
            def __init__(self, *a, **k):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def get(self, url, headers=None):
                return FakeResp({"data": [{"id": "gpt-4o"}]})

        class FakeResult:
            def __init__(self, rows):
                self._rows = rows
            def scalars(self):
                class R:
                    def __init__(self, rows):
                        self._rows = rows
                    def __iter__(self):
                        return iter(self._rows)
                return R(self._rows)

        class FakeKey:
            def __init__(self, provider_id, api_key):
                self.provider_id = provider_id
                self.api_key = api_key

        class FakeDB:
            async def execute(self, *a, **k):
                return FakeResult([FakeKey("openai", "sk-test")])

        with patch.object(httpx, "AsyncClient", lambda *a, **k: FakeClient()):
            models = asyncio.run(llm.list_models(FakeDB()))

        openai = [m for m in models if m.provider == "openai"]
        self.assertEqual([m.litellm_id for m in openai], ["openai/gpt-4o"])
        # No curated gpt-5 / gpt-5-mini fabricated alongside the live answer.
        self.assertNotIn("openai/gpt-5", {m.litellm_id for m in openai})

    def test_resolve_model_handles_dynamic_and_ollama_ids(self):
        dynamic_id = llm._model_id_for("gemini", "gemini/gemini-1.5-pro")
        resolved = llm._resolve_model(dynamic_id)
        self.assertEqual(resolved.provider, "gemini")
        self.assertEqual(resolved.litellm_id, "gemini/gemini-1.5-pro")

        ollama_resolved = llm._resolve_model("ollama:llama3.2")
        self.assertEqual(ollama_resolved.provider, "ollama")
        self.assertEqual(ollama_resolved.litellm_id, "ollama/llama3.2")

    def test_ollama_lists_only_locally_pulled_models(self):
        """Ollama must surface only real, pulled models — never a hard-coded
        default list (no 'random' offline models)."""
        import httpx

        class FakeResp:
            def __init__(self, data):
                self._data = data
            def raise_for_status(self):
                pass
            def json(self):
                return self._data

        class FakeClient:
            def __init__(self, *a, **k):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def get(self, url, headers=None):
                return FakeResp({"models": [{"name": "llama3.2"}, {"name": "mistral"}]})

        with patch.object(httpx, "AsyncClient", lambda *a, **k: FakeClient()):
            models = asyncio.run(llm.list_ollama_models())

        names = {m.litellm_id for m in models}
        self.assertEqual(names, {"ollama/llama3.2", "ollama/mistral"})
        # No fabrication of models the server didn't report.
        self.assertNotIn("ollama/llama3", names)

    def test_ollama_lists_nothing_when_server_unreachable(self):
        import httpx

        class FakeClient:
            def __init__(self, *a, **k):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def get(self, url, headers=None):
                raise httpx.ConnectError("refused")

        with patch.object(httpx, "AsyncClient", lambda *a, **k: FakeClient()):
            models = asyncio.run(llm.list_ollama_models())

        self.assertEqual(models, [])

    def test_ollama_tries_to_auto_start_when_down(self):
        """When the local Ollama server isn't up, list_ollama_models should
        attempt to auto-start it (so it connects with no manual steps) and
        re-probe before giving up."""
        import httpx

        calls = {"count": 0}

        class FakeClient:
            def __init__(self, *a, **k):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def get(self, url, headers=None):
                calls["count"] += 1
                raise httpx.ConnectError("refused")

        with patch.object(httpx, "AsyncClient", lambda *a, **k: FakeClient()), \
                patch("backend.providers.ollama._try_start_ollama") as start_mock:
            models = asyncio.run(llm.list_ollama_models())

        self.assertEqual(models, [])
        # Reached the server twice (initial probe + post auto-start probe).
        self.assertEqual(calls["count"], 5)
        start_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
