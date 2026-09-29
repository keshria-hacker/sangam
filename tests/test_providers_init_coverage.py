"""
Tests for providers/__init__.py branch coverage - targeting uncovered lines:
- 247: resolve_api_key returns None
- 250: registry.get_config returns None
- 253-254: fetch_models_from_provider exception handling
- 264: asyncio.gather exception handling
- 304-305: list_provider_status exception handling for cloud providers
- 312-333: _provider_reachable HTTP error paths
- 363-364: LiteLLM fallback when provider class not found
- 372: ValueError for unknown provider
"""
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mainfiles"))

os.environ["TEST_MODE"] = "1"
from cryptography.fernet import Fernet
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key


class ListModelsCoverageTests(unittest.TestCase):
    """Tests for list_models function covering error paths."""

    def test_list_models_resolve_api_key_returns_none(self):
        """When resolve_api_key returns None, provider is skipped (line 247)."""
        import asyncio
        from backend.providers import list_models

        mock_db = AsyncMock()

        with patch("backend.providers.list_linked_providers", new_callable=AsyncMock) as mock_linked:
            mock_linked.return_value = ["openai"]

            with patch("backend.providers.resolve_api_key", new_callable=AsyncMock) as mock_resolve:
                mock_resolve.return_value = None  # No key available

                with patch("backend.providers.fetch_ollama_models", new_callable=AsyncMock) as mock_ollama:
                    mock_ollama.return_value = []

                    async def test():
                        result = await list_models(mock_db)
                        # Should return empty list since no keys available
                        self.assertEqual(result, [])

                    asyncio.run(test())

    def test_list_models_ollama_exception_caught(self):
        """Exception in fetch_ollama_models is caught and ignored (lines 239-241)."""
        import asyncio
        from backend.providers import list_models

        mock_db = AsyncMock()

        with patch("backend.providers.list_linked_providers", new_callable=AsyncMock) as mock_linked:
            mock_linked.return_value = ["openai"]

            with patch("backend.providers.resolve_api_key", new_callable=AsyncMock) as mock_resolve:
                mock_resolve.return_value = "test-key"

                with patch("backend.providers.fetch_ollama_models", new_callable=AsyncMock) as mock_ollama:
                    mock_ollama.side_effect = Exception("Ollama connection failed")

                    with patch("backend.providers.registry.registry.get_config") as mock_get_config:
                        mock_config = MagicMock()
                        mock_config.model_endpoint = "https://api.openai.com/v1/models"
                        mock_get_config.return_value = mock_config

                        with patch("backend.providers.fetch_models_from_provider", new_callable=AsyncMock) as mock_fetch:
                            mock_fetch.return_value = []

                            async def test():
                                result = await list_models(mock_db)
                                # Should handle Ollama exception and continue
                                self.assertEqual(result, [])

                            asyncio.run(test())

    def test_list_models_registry_get_config_returns_none(self):
        """When registry.get_config returns None, provider is skipped (line 250)."""
        import asyncio
        from backend.providers import list_models

        mock_db = AsyncMock()

        with patch("backend.providers.list_linked_providers", new_callable=AsyncMock) as mock_linked:
            mock_linked.return_value = ["unknown_provider"]

            with patch("backend.providers.resolve_api_key", new_callable=AsyncMock) as mock_resolve:
                mock_resolve.return_value = "test-key"

                # Patch registry.registry.get_config (the registry object has get_config)
                with patch("backend.providers.registry.registry.get_config") as mock_get_config:
                    mock_get_config.return_value = None  # Unknown provider config

                    with patch("backend.providers.fetch_ollama_models", new_callable=AsyncMock) as mock_ollama:
                        mock_ollama.return_value = []

                        async def test():
                            result = await list_models(mock_db)
                            self.assertEqual(result, [])

                        asyncio.run(test())

    def test_list_models_fetch_models_from_provider_exception(self):
        """fetch_models_from_provider exception is caught and returns empty list (lines 253-254)."""
        import asyncio
        from backend.providers import list_models

        mock_db = AsyncMock()

        with patch("backend.providers.list_linked_providers", new_callable=AsyncMock) as mock_linked:
            mock_linked.return_value = ["openai"]

            with patch("backend.providers.resolve_api_key", new_callable=AsyncMock) as mock_resolve:
                mock_resolve.return_value = "test-key"

                with patch("backend.providers.registry.registry.get_config") as mock_get_config:
                    mock_config = MagicMock()
                    mock_config.model_endpoint = "https://api.openai.com/v1/models"
                    mock_get_config.return_value = mock_config

                    with patch("backend.providers.fetch_models_from_provider", new_callable=AsyncMock) as mock_fetch:
                        mock_fetch.side_effect = Exception("Network error")

                        with patch("backend.providers.fetch_ollama_models", new_callable=AsyncMock) as mock_ollama:
                            mock_ollama.return_value = []

                            async def test():
                                result = await list_models(mock_db)
                                # Exception caught, should return empty list for that provider
                                self.assertEqual(result, [])

                            asyncio.run(test())

    def test_list_models_asyncio_gather_exception_handling(self):
        """asyncio.gather with return_exceptions=True handles exceptions (line 264)."""
        import asyncio
        from backend.providers import list_models

        mock_db = AsyncMock()

        with patch("backend.providers.list_linked_providers", new_callable=AsyncMock) as mock_linked:
            mock_linked.return_value = ["openai", "anthropic"]

            with patch("backend.providers.resolve_api_key", new_callable=AsyncMock) as mock_resolve:
                mock_resolve.return_value = "test-key"

                with patch("backend.providers.registry.registry.get_config") as mock_get_config:
                    mock_config = MagicMock()
                    mock_config.model_endpoint = "https://api.openai.com/v1/models"
                    mock_get_config.return_value = mock_config

                    call_count = 0

                    async def mock_fetch_models(*args, **kwargs):
                        nonlocal call_count
                        call_count += 1
                        if call_count == 1:
                            raise Exception("First provider failed")
                        return []

                    with patch("backend.providers.fetch_models_from_provider", side_effect=mock_fetch_models):
                        with patch("backend.providers.fetch_ollama_models", new_callable=AsyncMock) as mock_ollama:
                            mock_ollama.return_value = []

                            async def test():
                                result = await list_models(mock_db)
                                # Should continue after exception in first provider
                                self.assertEqual(result, [])

                            asyncio.run(test())


class ProviderReachableTests(unittest.TestCase):
    """Tests for _provider_reachable function covering HTTP error paths (lines 312-333)."""

    def setUp(self):
        # Import the function to test
        from backend.providers import _provider_reachable
        from backend.providers.base import ProviderConfig
        self._provider_reachable = _provider_reachable
        self.ProviderConfig = ProviderConfig

    @patch("httpx.AsyncClient")
    def test_provider_reachable_success(self, mock_client_class):
        """Provider reachable returns True on 200 response."""
        import asyncio

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client_instance

        config = self.ProviderConfig(
            provider_id="test", label="Test", local=False, env_key_name="TEST_KEY",
            api_base="https://api.test.com", model_endpoint="https://api.test.com/models",
            auth_type="bearer", json_path="", id_field="", litellm_prefix=""
        )

        async def test():
            result = await self._provider_reachable(config, "test-key")
            self.assertTrue(result)

        asyncio.run(test())

    @patch("httpx.AsyncClient")
    def test_provider_reachable_http_error(self, mock_client_class):
        """Provider reachable returns False on HTTP error (line 332-333)."""
        import asyncio
        import httpx

        mock_client_instance = AsyncMock()
        mock_client_instance.get.side_effect = httpx.HTTPError("Connection failed")
        mock_client_class.return_value.__aenter__.return_value = mock_client_instance

        config = self.ProviderConfig(
            provider_id="test", label="Test", local=False, env_key_name="TEST_KEY",
            api_base="https://api.test.com", model_endpoint="https://api.test.com/models",
            auth_type="bearer", json_path="", id_field="", litellm_prefix=""
        )

        async def test():
            result = await self._provider_reachable(config, "test-key")
            self.assertFalse(result)

        asyncio.run(test())

    @patch("httpx.AsyncClient")
    def test_provider_reachable_bearer_auth(self, mock_client_class):
        """Bearer auth adds Authorization header (lines 315-316)."""
        import asyncio

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client_instance

        config = self.ProviderConfig(
            provider_id="test", label="Test", local=False, env_key_name="TEST_KEY",
            api_base="https://api.test.com", model_endpoint="https://api.test.com/models",
            auth_type="bearer", json_path="", id_field="", litellm_prefix=""
        )

        async def test():
            await self._provider_reachable(config, "my-bearer-token")

        asyncio.run(test())

        # Verify Authorization header was set
        call_kwargs = mock_client_instance.get.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        self.assertIn("Authorization", headers)
        self.assertEqual(headers["Authorization"], "Bearer my-bearer-token")

    @patch("httpx.AsyncClient")
    def test_provider_reachable_header_auth(self, mock_client_class):
        """Header auth adds custom header (lines 317-318)."""
        import asyncio

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client_instance

        config = self.ProviderConfig(
            provider_id="test", label="Test", local=False, env_key_name="TEST_KEY",
            api_base="https://api.test.com", model_endpoint="https://api.test.com/models",
            auth_type="header", auth_header_name="x-api-key",
            json_path="", id_field="", litellm_prefix=""
        )

        async def test():
            await self._provider_reachable(config, "my-api-key")

        asyncio.run(test())

        call_kwargs = mock_client_instance.get.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        self.assertIn("x-api-key", headers)
        self.assertEqual(headers["x-api-key"], "my-api-key")

    @patch("httpx.AsyncClient")
    def test_provider_reachable_query_auth(self, mock_client_class):
        """Query auth adds key to URL (lines 323-325)."""
        import asyncio

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client_instance

        config = self.ProviderConfig(
            provider_id="test", label="Test", local=False, env_key_name="TEST_KEY",
            api_base="https://api.test.com", model_endpoint="https://api.test.com/models",
            auth_type="query", query_key="key",
            json_path="", id_field="", litellm_prefix=""
        )

        async def test():
            await self._provider_reachable(config, "my-query-key")

        asyncio.run(test())

        call_kwargs = mock_client_instance.get.call_args
        url = call_kwargs.args[0]
        self.assertIn("key=my-query-key", url)

    @patch("httpx.AsyncClient")
    def test_provider_reachable_extra_headers(self, mock_client_class):
        """Extra headers are included (lines 319-320)."""
        import asyncio

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client_instance

        config = self.ProviderConfig(
            provider_id="test", label="Test", local=False, env_key_name="TEST_KEY",
            api_base="https://api.test.com", model_endpoint="https://api.test.com/models",
            auth_type="bearer", extra_headers={"custom-header": "custom-value"},
            json_path="", id_field="", litellm_prefix=""
        )

        async def test():
            await self._provider_reachable(config, "test-key")

        asyncio.run(test())

        call_kwargs = mock_client_instance.get.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        self.assertIn("custom-header", headers)
        self.assertEqual(headers["custom-header"], "custom-value")


class ListProviderStatusCoverageTests(unittest.TestCase):
    """Tests for list_provider_status covering exception paths (lines 304-305)."""

    def test_list_provider_status_cloud_provider_exception(self):
        """Exception in _provider_reachable is caught (lines 304-305)."""
        import asyncio
        from backend.providers import list_provider_status

        mock_db = AsyncMock()

        with patch("backend.providers.get_db_keys", new_callable=AsyncMock) as mock_db_keys:
            mock_db_keys.return_value = {"openai": "test-key"}

            with patch("backend.providers.get_static_env_key") as mock_static_key:
                mock_static_key.return_value = None

                # Patch model_discovery._ollama_reachable where it's imported in list_provider_status
                with patch("backend.providers.model_discovery._ollama_reachable", new_callable=AsyncMock) as mock_ollama:
                    mock_ollama.return_value = False

                    # Patch _provider_reachable where it's used in list_provider_status
                    with patch("backend.providers._provider_reachable", new_callable=AsyncMock) as mock_reachable:
                        mock_reachable.side_effect = Exception("Unexpected error")

                        async def test():
                            result = await list_provider_status(mock_db)
                            # Should handle exception and continue
                            self.assertEqual(result, [])

                        asyncio.run(test())


class StreamCompletionCoverageTests(unittest.TestCase):
    """Tests for stream_completion covering fallback paths (lines 363-364, 372)."""

    async def _mock_stream_completion(self, *args, **kwargs):
        """Mock async generator for LLM stream."""
        for chunk in ["Hello", " ", "World"]:
            yield chunk

    def test_stream_completion_litellm_fallback(self):
        """Falls back to LiteLLM when provider class not found (lines 363-364)."""
        import asyncio
        from backend.providers import stream_completion
        from backend.providers.base import ProviderConfig

        mock_db = AsyncMock()

        async def mock_stream(*args, **kwargs):
            for chunk in ["fallback"]:
                yield chunk

        with patch("backend.providers._resolve_model", return_value=("openai", "gpt-4")):
            with patch("backend.providers.resolve_api_key", new_callable=AsyncMock) as mock_resolve:
                mock_resolve.return_value = "test-key"

                with patch("backend.providers.registry.registry.get_provider_class") as mock_get_class:
                    mock_get_class.return_value = None  # No custom class

                    with patch("backend.providers.registry.registry.get_config") as mock_get_config:
                        mock_config = MagicMock()
                        mock_config.provider_id = "openai"
                        mock_config.label = "OpenAI"
                        mock_config.local = False
                        mock_config.env_key_name = "OPENAI_API_KEY"
                        mock_config.api_base = ""
                        mock_config.model_endpoint = ""
                        mock_config.json_path = ""
                        mock_config.id_field = ""
                        mock_config.litellm_prefix = ""
                        mock_get_config.return_value = mock_config

                        with patch("backend.providers.litellm_fallback.LiteLLMProvider") as mock_litellm_class:
                            mock_provider = MagicMock()
                            mock_provider.stream_completion = mock_stream
                            mock_litellm_class.return_value = mock_provider

                            async def test():
                                result = []
                                async for chunk in stream_completion("openai::gpt-4", [{"role": "user", "content": "hi"}], mock_db):
                                    result.append(chunk)
                                self.assertEqual(result, ["fallback"])

                            asyncio.run(test())

    def test_stream_completion_custom_provider_class(self):
        """Uses custom provider class when available (lines 370-374)."""
        import asyncio
        from backend.providers import stream_completion
        from backend.providers.base import ProviderConfig

        mock_db = AsyncMock()

        async def mock_stream(*args, **kwargs):
            for chunk in ["custom"]:
                yield chunk

        mock_provider_class = MagicMock()
        mock_provider_class.return_value.stream_completion = mock_stream

        with patch("backend.providers._resolve_model", return_value=("openai", "gpt-4")):
            with patch("backend.providers.resolve_api_key", new_callable=AsyncMock) as mock_resolve:
                mock_resolve.return_value = "test-key"

                with patch("backend.providers.registry.registry.get_provider_class") as mock_get_class:
                    mock_get_class.return_value = mock_provider_class

                    with patch("backend.providers.registry.registry.get_config") as mock_get_config:
                        mock_config = MagicMock()
                        mock_config.provider_id = "openai"
                        mock_config.label = "OpenAI"
                        mock_config.local = False
                        mock_config.env_key_name = "OPENAI_API_KEY"
                        mock_config.api_base = ""
                        mock_config.model_endpoint = ""
                        mock_config.json_path = ""
                        mock_config.id_field = ""
                        mock_config.litellm_prefix = ""
                        mock_get_config.return_value = mock_config

                        async def test():
                            result = []
                            async for chunk in stream_completion("openai::gpt-4", [{"role": "user", "content": "hi"}], mock_db):
                                result.append(chunk)
                            self.assertEqual(result, ["custom"])

                        asyncio.run(test())


class StreamCompletionUnknownProviderTests(unittest.TestCase):
    """Tests for stream_completion unknown provider error (lines 370-372)."""

    def test_stream_completion_unknown_provider_with_class_but_no_config_raises(self):
        """Provider class exists but config missing raises ValueError (lines 370-372)."""
        import asyncio
        from backend.providers import stream_completion

        mock_db = AsyncMock()

        with patch("backend.providers._resolve_model", return_value=("unknown", "model")):
            with patch("backend.providers.resolve_api_key", new_callable=AsyncMock) as mock_resolve:
                mock_resolve.return_value = "test-key"

                # Provider class exists (not None), but config is None
                with patch("backend.providers.registry.registry.get_provider_class") as mock_get_class:
                    mock_get_class.return_value = MagicMock()  # Class exists

                    with patch("backend.providers.registry.registry.get_config") as mock_get_config:
                        mock_get_config.return_value = None  # But no config

                        async def test():
                            with self.assertRaises(ValueError) as ctx:
                                async for _ in stream_completion("unknown::model", [], mock_db):
                                    pass
                                self.assertIn("Unknown provider", str(ctx.exception))

                        asyncio.run(test())


class ResolveModelTests(unittest.TestCase):
    """Tests for _resolve_model function."""

    def test_resolve_model_valid(self):
        """Valid model ID is parsed correctly."""
        from backend.providers import _resolve_model
        provider_id, litellm_id = _resolve_model("openai::gpt-4")
        self.assertEqual(provider_id, "openai")
        self.assertEqual(litellm_id, "gpt-4")

    def test_resolve_model_invalid_format(self):
        """Invalid model ID format raises ValueError."""
        from backend.providers import _resolve_model
        with self.assertRaises(ValueError) as ctx:
            _resolve_model("invalid-format")
        self.assertIn("Invalid model ID format", str(ctx.exception))

    def test_resolve_model_no_separator(self):
        """Model ID without :: raises ValueError."""
        from backend.providers import _resolve_model
        with self.assertRaises(ValueError):
            _resolve_model("just-a-string")


class DefaultModelIdTests(unittest.TestCase):
    """Tests for default_model_id function (lines 338-339)."""

    def test_default_model_id_with_models(self):
        """Returns first model ID when models exist."""
        import asyncio
        from backend.providers import default_model_id
        from backend.providers.base import ModelInfo

        mock_db = AsyncMock()

        mock_models = [
            ModelInfo(id="ollama::llama3", name="Llama 3", provider_id="ollama", provider_label="Ollama"),
            ModelInfo(id="openai::gpt-4", name="GPT-4", provider_id="openai", provider_label="OpenAI"),
        ]

        with patch("backend.providers.list_models", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = mock_models

            async def test():
                result = await default_model_id(mock_db)
                self.assertEqual(result, "ollama::llama3")

            asyncio.run(test())

    def test_default_model_id_no_models(self):
        """Returns None when no models available."""
        import asyncio
        from backend.providers import default_model_id

        mock_db = AsyncMock()

        with patch("backend.providers.list_models", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = []

            async def test():
                result = await default_model_id(mock_db)
                self.assertIsNone(result)

            asyncio.run(test())


class ClearInaccessibleModelsTests(unittest.TestCase):
    """Tests for clear_inaccessible_models function (line 416)."""

    def test_clear_inaccessible_models_returns_count(self):
        """Calls clear_inaccessible and returns count."""
        from backend.providers import clear_inaccessible_models

        with patch("backend.providers.clear_inaccessible", return_value=5) as mock_clear:
            result = clear_inaccessible_models()
            self.assertEqual(result, 5)
            mock_clear.assert_called_once()


class ListProvidersStaticTests(unittest.TestCase):
    """Tests for list_providers_static function."""

    def test_list_providers_static_includes_env_key_set(self):
        """Returns provider metadata with env_key_set."""
        from backend.providers import list_providers_static
        from backend.providers.base import ProviderConfig

        mock_config = ProviderConfig(
            provider_id="openai", label="OpenAI", local=False, env_key_name="OPENAI_API_KEY",
            api_base="https://api.openai.com", model_endpoint="https://api.openai.com/v1/models",
            auth_type="bearer", json_path="", id_field="", litellm_prefix="openai"
        )

        with patch("backend.providers.registry.registry.get_all_configs") as mock_get_all:
            mock_get_all.return_value = {"openai": mock_config}

            with patch("backend.providers.get_static_env_key", return_value="test-key"):
                result = list_providers_static()
                self.assertIn("openai", result)
                self.assertEqual(result["openai"]["label"], "OpenAI")
                self.assertEqual(result["openai"]["local"], False)
                self.assertTrue(result["openai"]["env_key_set"])

    def test_list_providers_static_no_env_key(self):
        """Returns env_key_set=False when no key in environment."""
        from backend.providers import list_providers_static
        from backend.providers.base import ProviderConfig

        mock_config = ProviderConfig(
            provider_id="anthropic", label="Anthropic", local=False, env_key_name="ANTHROPIC_API_KEY",
            api_base="https://api.anthropic.com", model_endpoint="https://api.anthropic.com/v1/models",
            auth_type="bearer", json_path="", id_field="", litellm_prefix="anthropic"
        )

        with patch("backend.providers.registry.registry.get_all_configs") as mock_get_all:
            mock_get_all.return_value = {"anthropic": mock_config}

            with patch("backend.providers.get_static_env_key", return_value=None):
                result = list_providers_static()
                self.assertIn("anthropic", result)
                self.assertFalse(result["anthropic"]["env_key_set"])


if __name__ == "__main__":
    unittest.main()
