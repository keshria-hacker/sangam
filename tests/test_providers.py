"""
Comprehensive unit tests for provider modules.

Tests cover:
- BaseProvider class and interface
- OpenAICompatible provider
- Ollama provider
- Key resolver
- Model discovery
- Provider registry
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mainfiles"))

# Enable test mode
os.environ["TEST_MODE"] = "1"
from cryptography.fernet import Fernet
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key

from backend.providers.base import BaseProvider, ModelInfo, ProviderConfig
from backend.providers.key_resolver import get_db_keys, get_static_env_key, resolve_api_key
from backend.providers.model_discovery import fetch_models_from_provider, fetch_ollama_models
from backend.providers.ollama import OllamaProvider
from backend.providers.openai_compatible import OpenAICompatibleProvider
from backend.providers.registry import ProviderRegistry
from backend.database import reset_db, AsyncSessionLocal


def _make_ollama_config() -> ProviderConfig:
    """Create an Ollama provider config for testing."""
    return ProviderConfig(
        provider_id="ollama",
        label="Ollama",
        local=True,
        env_key_name=None,
        api_base="http://localhost:11434",
        model_endpoint="http://localhost:11434/api/tags",
        auth_type="none",
        json_path="models",
        id_field="name",
        litellm_prefix="ollama/",
    )


def _make_openai_config() -> ProviderConfig:
    """Create an OpenAI-compatible provider config for testing."""
    return ProviderConfig(
        provider_id="test",
        label="Test Provider",
        local=False,
        env_key_name="TEST_API_KEY",
        api_base="http://localhost:8000/v1",
        model_endpoint="http://localhost:8000/v1/models",
        auth_type="bearer",
        json_path="data",
        id_field="id",
        litellm_prefix="test/",
    )


class TestBaseProvider(unittest.TestCase):
    """Tests for BaseProvider abstract class."""

    def test_base_provider_is_abstract(self):
        """BaseProvider should not be instantiable directly."""
        with self.assertRaises(TypeError):
            BaseProvider()

    def test_base_provider_subclass_must_implement(self):
        """Subclasses must implement abstract methods."""
        class IncompleteProvider(BaseProvider):
            pass

        with self.assertRaises(TypeError):
            IncompleteProvider()


class TestKeyResolver(unittest.IsolatedAsyncioTestCase):
    """Tests for resolve_api_key function."""

    async def asyncSetUp(self):
        await reset_db()
        self.session = AsyncSessionLocal()

    async def asyncTearDown(self):
        await self.session.close()

    async def test_resolve_api_key_returns_none_for_unknown_provider(self):
        """Should return None for unknown provider."""
        result = await resolve_api_key("unknown_provider", self.session)
        self.assertIsNone(result)

    async def test_resolve_api_key_returns_none_for_provider_without_key(self):
        """Should return None for provider with no API key set."""
        result = await resolve_api_key("ollama", self.session)
        self.assertIsNone(result)

    async def test_get_db_keys_returns_dict(self):
        """Should return dict of provider keys from DB."""
        keys = await get_db_keys(self.session)
        self.assertIsInstance(keys, dict)

    def test_get_static_env_key_returns_none_for_unknown(self):
        """Should return None for unknown provider ID."""
        result = get_static_env_key("unknown_provider_id_that_does_not_exist")
        self.assertIsNone(result)


class TestOllamaProvider(unittest.IsolatedAsyncioTestCase):
    """Tests for OllamaProvider."""

    async def asyncSetUp(self):
        await reset_db()
        self.session = AsyncSessionLocal()

    async def asyncTearDown(self):
        await self.session.close()

    def test_ollama_provider_creation(self):
        """Test OllamaProvider can be instantiated with config."""
        config = _make_ollama_config()
        provider = OllamaProvider(config)
        self.assertEqual(provider.config.provider_id, "ollama")
        self.assertEqual(provider.config.label, "Ollama")

    def test_ollama_provider_requires_config(self):
        """Test OllamaProvider requires config parameter."""
        with self.assertRaises(TypeError):
            OllamaProvider()

    @patch('backend.providers.ollama.httpx.AsyncClient')
    async def test_list_models_empty_on_connection_error(self, mock_client):
        """Should return empty list on connection error."""
        import httpx

        mock_client.return_value.__aenter__.return_value.get.side_effect = httpx.ConnectError("Connection refused")

        config = _make_ollama_config()
        provider = OllamaProvider(config)
        models = await provider.list_models()

        self.assertEqual(models, [])

    @patch('backend.providers.ollama.httpx.AsyncClient')
    async def test_list_models_filters_non_chat(self, mock_client):
        """Should filter out non-chat models."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3:latest", "details": {"families": ["llama"], "parameter_size": "8B"}},
                {"name": "nomic-embed-text:latest", "details": {"families": ["bert"], "parameter_size": "137M"}},
            ]
        }
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

        config = _make_ollama_config()
        provider = OllamaProvider(config)
        models = await provider.list_models()

        # Only llama3:latest should be returned (chat model)
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].litellm_id, "ollama/llama3:latest")


class TestOpenAICompatibleProvider(unittest.IsolatedAsyncioTestCase):
    """Tests for OpenAICompatibleProvider."""

    async def asyncSetUp(self):
        await reset_db()
        self.session = AsyncSessionLocal()

    async def asyncTearDown(self):
        await self.session.close()

    def test_openai_compatible_creation(self):
        """Test OpenAICompatibleProvider can be instantiated with config."""
        config = _make_openai_config()
        provider = OpenAICompatibleProvider(config, api_key="test-key")
        self.assertEqual(provider.config.provider_id, "test")
        self.assertEqual(provider.api_key, "test-key")

    def test_openai_compatible_requires_config(self):
        """Test OpenAICompatibleProvider requires config parameter."""
        with self.assertRaises(TypeError):
            OpenAICompatibleProvider()

    @patch('backend.providers.openai_compatible.httpx.AsyncClient')
    async def test_list_models_handles_error(self, mock_client):
        """Should handle API errors gracefully."""
        import httpx

        mock_client.return_value.__aenter__.return_value.get.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=MagicMock(status_code=404)
        )

        config = _make_openai_config()
        provider = OpenAICompatibleProvider(config, api_key="test-key")
        models = await provider.list_models()

        self.assertEqual(models, [])

    @patch('backend.providers.openai_compatible.httpx.AsyncClient')
    async def test_list_models_filters_completion_models(self, mock_client):
        """Should filter out non-chat models based on NON_CHAT_MARKERS."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "gpt-4", "owned_by": "openai"},
                {"id": "text-embedding-ada-002", "owned_by": "openai"},  # embedding model - should be filtered
                {"id": "gpt-3.5-turbo", "owned_by": "openai"},
            ]
        }
        mock_client.return_value.__aenter__.return_value.get.return_value = mock_response

        config = _make_openai_config()
        provider = OpenAICompatibleProvider(config, api_key="test-key")
        models = await provider.list_models()

        # Should keep gpt-4 and gpt-3.5-turbo, filter out text-embedding-ada-002
        model_ids = [m.litellm_id for m in models]
        self.assertIn("test/gpt-4", model_ids)
        self.assertIn("test/gpt-3.5-turbo", model_ids)
        self.assertNotIn("test/text-embedding-ada-002", model_ids)


class TestProviderRegistry(unittest.IsolatedAsyncioTestCase):
    """Tests for ProviderRegistry."""

    async def asyncSetUp(self):
        await reset_db()
        self.session = AsyncSessionLocal()
        # Initialize the registry
        from backend.providers.registry import init_provider_registry
        init_provider_registry()
        self.registry = ProviderRegistry()

    async def asyncTearDown(self):
        await self.session.close()

    def test_registry_creation(self):
        """Test registry can be created."""
        self.assertIsNotNone(self.registry)

    def test_get_all_configs(self):
        """Should return dict of all provider configs."""
        configs = self.registry.get_all_configs()
        self.assertIsInstance(configs, dict)
        self.assertGreater(len(configs), 0)

        # Check structure
        for pid, config in configs.items():
            self.assertEqual(pid, config.provider_id)
            self.assertIsInstance(config.label, str)
            self.assertIsInstance(config.local, bool)

    def test_get_provider_config(self):
        """Should return config for known provider."""
        config = self.registry.get_config("ollama")
        self.assertIsNotNone(config)
        self.assertEqual(config.provider_id, "ollama")

    def test_get_provider_config_unknown(self):
        """Should return None for unknown provider."""
        config = self.registry.get_config("unknown_provider")
        self.assertIsNone(config)

    def test_get_provider_config_openai(self):
        """Should return config for OpenAI."""
        config = self.registry.get_config("openai")
        self.assertIsNotNone(config)
        self.assertEqual(config.provider_id, "openai")

    def test_all_provider_ids(self):
        """Should return list of all provider IDs."""
        ids = self.registry.all_provider_ids()
        self.assertIsInstance(ids, list)
        self.assertGreater(len(ids), 0)
        self.assertIn("ollama", ids)
        self.assertIn("openai", ids)

    def test_all_non_local_ids(self):
        """Should return list of non-local provider IDs."""
        ids = self.registry.all_non_local_ids()
        self.assertIsInstance(ids, list)
        self.assertIn("openai", ids)
        self.assertIn("anthropic", ids)
        self.assertNotIn("ollama", ids)


class TestModelDiscovery(unittest.IsolatedAsyncioTestCase):
    """Tests for model discovery module."""

    async def asyncSetUp(self):
        await reset_db()
        self.session = AsyncSessionLocal()

    async def asyncTearDown(self):
        await self.session.close()

    def test_fetch_ollama_models_importable(self):
        """fetch_ollama_models should be importable."""
        from backend.providers.model_discovery import fetch_ollama_models
        self.assertTrue(callable(fetch_ollama_models))

    @patch('backend.providers.model_discovery.httpx.AsyncClient')
    async def test_fetch_models_from_provider_empty_on_error(self, mock_client):
        """Should return empty list on API error."""
        import httpx

        mock_client.return_value.__aenter__.return_value.get.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=MagicMock(status_code=404)
        )

        config = _make_openai_config()
        config.provider_id = "test"

        models = await fetch_models_from_provider("test-key", config)

        self.assertEqual(models, [])


class TestProviderInit(unittest.TestCase):
    """Tests for providers __init__ module."""

    def test_imports_work(self):
        """All provider modules should import without error."""
        from backend.providers.ollama import OllamaProvider
        from backend.providers.openai_compatible import OpenAICompatibleProvider
        from backend.providers.registry import ProviderRegistry
        from backend.providers.model_discovery import (
            fetch_models_from_provider,
            fetch_ollama_models,
        )
        from backend.providers.key_resolver import (
            resolve_api_key,
            get_db_keys,
            get_static_env_key,
            list_linked_providers,
        )
        from backend.providers.base import BaseProvider
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()