"""
Comprehensive tests for llm.py — Unified LLM Provider Facade.

Tests cover:
- _resolve_model function (various model ID formats)
- stream_completion function (provider routing, error handling)
- list_models, list_provider_status, default_model_id
- get_db_keys, resolve_api_key
- _linked_providers function
- sanitize_error function (API key redaction)
- fetch_models_from_provider (legacy wrapper)
- _fetch_provider_models (legacy wrapper)
- Ollama functions (list_ollama_models, _try_start_ollama, _cleanup_ollama)
- Provider registry and model discovery functions
- __getattr__ lazy loading
"""
import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Enable test mode
os.environ["TEST_MODE"] = "1"
from cryptography.fernet import Fernet
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key

# Use a temporary directory for ChromaDB in tests
import tempfile
test_chroma_dir = Path(tempfile.gettempdir()) / "test_chromadb_llm"
os.environ["CHROMA_DB_PATH"] = str(test_chroma_dir)

import backend.llm as llm
from backend.providers import (
    CURATED_MODELS,
    MODELS,
    PROVIDERS,
    ModelInfo,
    ProviderConfig,
)
from backend.providers.base import ProviderConfig as BaseProviderConfig


class ResolveModelTests(unittest.TestCase):
    """Tests for _resolve_model function."""

    def test_resolve_ollama_model(self):
        """ollama:model format returns ModelInfo with ollama provider."""
        model = llm._resolve_model("ollama:llama3.1")
        self.assertIsNotNone(model)
        self.assertEqual(model.provider_id, "ollama")
        self.assertEqual(model.name, "llama3.1")
        self.assertEqual(model.litellm_id, "ollama/llama3.1")
        self.assertEqual(model.id, "ollama::llama3.1")

    def test_resolve_ollama_model_with_tags(self):
        """ollama:model:tag format works correctly."""
        model = llm._resolve_model("ollama:llama3.1:latest")
        self.assertIsNotNone(model)
        self.assertEqual(model.provider_id, "ollama")
        self.assertEqual(model.name, "llama3.1:latest")

    def test_resolve_provider_litellm_format(self):
        """provider::litellm_id format resolves from CURATED_MODELS."""
        # Find a model in CURATED_MODELS
        for m in CURATED_MODELS.values():
            if m.litellm_id:
                model_id = f"{m.provider_id}::{m.litellm_id}"
                model = llm._resolve_model(model_id)
                self.assertIsNotNone(model)
                self.assertEqual(model.litellm_id, m.litellm_id)
                self.assertEqual(model.provider_id, m.provider_id)
                return

    def test_resolve_provider_litellm_format_fallback(self):
        """provider::litellm_id with unknown model creates basic ModelInfo."""
        model = llm._resolve_model("openai::openai/gpt-4o-mini")
        self.assertIsNotNone(model)
        self.assertEqual(model.provider_id, "openai")
        self.assertEqual(model.litellm_id, "openai/gpt-4o-mini")

    def test_resolve_none_for_invalid_format(self):
        """Invalid model ID format returns None."""
        result = llm._resolve_model("invalid-format")
        self.assertIsNone(result)

    def test_resolve_none_for_empty_string(self):
        """Empty string returns None."""
        result = llm._resolve_model("")
        self.assertIsNone(result)

    def test_resolve_handles_missing_curated(self):
        """Provider not in CURATED_MODELS falls back correctly."""
        model = llm._resolve_model("unknown::some/model")
        self.assertIsNotNone(model)
        self.assertEqual(model.provider_id, "unknown")


class SanitizeErrorTests(unittest.TestCase):
    """Tests for sanitize_error function."""

    def test_redacts_openai_key(self):
        """OpenAI API key pattern is redacted."""
        msg = "Error: sk-proj-abcdefghijklmnopqrstuvwxyz1234567890"
        result = llm.sanitize_error(msg)
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("sk-proj-", result)

    def test_redacts_anthropic_key(self):
        """Anthropic API key pattern is redacted."""
        msg = "Error: sk-ant-api03-abcdefghijklmnopqrstuvwxyz123456"
        result = llm.sanitize_error(msg)
        self.assertIn("***REDACTED***", result)

    def test_redacts_gemini_key(self):
        """Gemini API key pattern is redacted."""
        msg = "Error: AIzaSyAbcdefghijklmnopqrstuvwxyz1234567890AB"
        result = llm.sanitize_error(msg)
        self.assertIn("***REDACTED***", result)

    def test_redacts_nvidia_key(self):
        """NVIDIA API key pattern is redacted."""
        msg = "Error: nvapi-abcdefghijklmnopqrstuvwxyz123456"
        result = llm.sanitize_error(msg)
        self.assertIn("***REDACTED***", result)

    def test_redacts_together_key(self):
        """Together AI API key pattern is redacted."""
        msg = "Error: tgp_v1_abcdefghijklmnopqrstuvwxyz123456"
        result = llm.sanitize_error(msg)
        self.assertIn("***REDACTED***", result)

    def test_redacts_groq_key(self):
        """Groq API key pattern is redacted."""
        msg = "Error: gsk_abcdefghijklmnopqrstuvwxyz123456"
        result = llm.sanitize_error(msg)
        self.assertIn("***REDACTED***", result)

    def test_redacts_openrouter_key(self):
        """OpenRouter API key pattern is redacted."""
        msg = "Error: sk-or-v1-abcdefghijklmnopqrstuvwxyz123456"
        result = llm.sanitize_error(msg)
        self.assertIn("***REDACTED***", result)

    def test_redacts_base64_key(self):
        """Base64-like key patterns are redacted (40+ chars)."""
        msg = "Error: YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXpBQkNERUZH"
        result = llm.sanitize_error(msg)
        self.assertIn("***REDACTED***", result)

    def test_redacts_hex_key(self):
        """Long hex strings are redacted (40+ chars)."""
        msg = "Error: abcdef1234567890abcdef1234567890abcdef123456"
        result = llm.sanitize_error(msg)
        self.assertIn("***REDACTED***", result)

    def test_redacts_bearer_token(self):
        """Bearer tokens are redacted."""
        msg = "Error: Bearer sk-abcdefghijklmnopqrstuvwxyz123456"
        result = llm.sanitize_error(msg)
        self.assertIn("***REDACTED***", result)

    def test_multiple_keys_redacted(self):
        """Multiple keys in one message all get redacted."""
        msg = "sk-proj-abcdefghijklmnopqrst1234567890 and sk-ant-api03-abcdefghijklmnopqrst123456 and AIzaSyAbcdefghijklmnopqrstuvwxyz1234567890AB"
        result = llm.sanitize_error(msg)
        self.assertEqual(result.count("***REDACTED***"), 3)

    def test_preserves_non_key_text(self):
        """Non-key text is preserved."""
        msg = "Connection timeout to api.openai.com"
        result = llm.sanitize_error(msg)
        self.assertEqual(result, msg)

    def test_empty_string(self):
        """Empty string returns empty string."""
        result = llm.sanitize_error("")
        self.assertEqual(result, "")


class LinkedProvidersTests(unittest.TestCase):
    """Tests for _linked_providers function."""

    def test_empty_keys_returns_only_env_providers(self):
        """Empty keys returns providers with env keys."""
        with patch.dict("backend.llm.PROVIDERS", {
            "openai": {"local": False, "env_key": "OPENAI_API_KEY"},
            "ollama": {"local": True},
            "custom": {"local": False, "env_key": None},
        }, clear=True):
            result = llm._linked_providers({})
            self.assertIn("openai", result)
            self.assertNotIn("ollama", result)
            self.assertNotIn("custom", result)

    def test_keys_matches_linked(self):
        """Keys with matching provider IDs are linked."""
        with patch.dict("backend.llm.PROVIDERS", {
            "openai": {"local": False, "env_key": "OPENAI_API_KEY"},
            "anthropic": {"local": False, "env_key": "ANTHROPIC_API_KEY"},
        }, clear=True):
            result = llm._linked_providers({"openai": "sk-test"})
            self.assertIn("openai", result)

    def test_env_key_providers_linked(self):
        """Providers with env_key set are linked even without DB key."""
        with patch.dict("backend.llm.PROVIDERS", {
            "openai": {"local": False, "env_key": "OPENAI_API_KEY"},
        }, clear=True):
            # Pretend env var is set
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env"}):
                result = llm._linked_providers({})
                self.assertIn("openai", result)

    def test_local_providers_excluded(self):
        """Local providers (ollama) are always excluded."""
        with patch.dict("backend.llm.PROVIDERS", {
            "ollama": {"local": True, "env_key": None},
            "lmstudio": {"local": True, "env_key": None},
        }, clear=True):
            result = llm._linked_providers({"ollama": "key"})
            self.assertNotIn("ollama", result)
            self.assertNotIn("lmstudio", result)


class FetchModelsFromProviderTests(unittest.IsolatedAsyncioTestCase):
    """Tests for fetch_models_from_provider legacy wrapper."""

    async def test_fetch_models_returns_dicts(self):
        """Returns list of dicts with expected fields."""
        mock_models = [
            ModelInfo(
                id="gpt-4o",
                name="GPT-4o",
                provider_id="openai",
                provider_label="OpenAI",
                litellm_id="openai/gpt-4o",
                model_id="gpt-4o",
            ),
            ModelInfo(
                id="gpt-4o-mini",
                name="GPT-4o Mini",
                provider_id="openai",
                provider_label="OpenAI",
                litellm_id="openai/gpt-4o-mini",
                model_id="gpt-4o-mini",
            ),
        ]

        with patch("backend.providers.model_discovery.fetch_models_from_provider", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_models

            result = await llm.fetch_models_from_provider(
                api_key="sk-test",
                endpoint_url="https://api.openai.com/v1/models",
                provider_id="openai",
                provider_label="OpenAI",
            )

            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 2)
            for item in result:
                self.assertIn("id", item)
                self.assertIn("name", item)
                self.assertIn("provider", item)
                self.assertIn("provider_label", item)
                self.assertIn("description", item)
                self.assertIn("litellm_id", item)

    async def test_fetch_models_deduplicates(self):
        """Deduplicates models by raw ID."""
        mock_models = [
            ModelInfo(
                id="gpt-4o",
                name="GPT-4o",
                provider_id="openai",
                provider_label="OpenAI",
                litellm_id="openai/gpt-4o",
                model_id="gpt-4o",
            ),
            ModelInfo(
                id="gpt-4o",
                name="GPT-4o Duplicate",
                provider_id="openai",
                provider_label="OpenAI",
                litellm_id="openai/gpt-4o",
                model_id="gpt-4o",
            ),
        ]

        with patch("backend.providers.model_discovery.fetch_models_from_provider", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_models

            result = await llm.fetch_models_from_provider(
                api_key="sk-test",
                endpoint_url="https://api.openai.com/v1/models",
                provider_id="openai",
                provider_label="OpenAI",
            )

            self.assertEqual(len(result), 1)


class FetchProviderModelsTests(unittest.IsolatedAsyncioTestCase):
    """Tests for _fetch_provider_models legacy wrapper."""

    async def test_fetch_openai_models(self):
        """Fetches models from OpenAI."""
        mock_models = [
            ModelInfo(
                id="gpt-4o",
                name="GPT-4o",
                provider_id="openai",
                provider_label="OpenAI",
                litellm_id="openai/gpt-4o",
                model_id="gpt-4o",
            ),
        ]

        with patch("backend.providers.list_providers_static", return_value={"openai": {}}):
            with patch("backend.providers.model_discovery.fetch_models_from_provider", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = mock_models

                result = await llm._fetch_provider_models("openai", "sk-test")

                self.assertIsInstance(result, list)
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0], "openai/gpt-4o")

    async def test_fetch_gemini_models(self):
        """Fetches models from Gemini."""
        mock_models = [
            ModelInfo(
                id="gemini-1.5-pro",
                name="Gemini 1.5 Pro",
                provider_id="gemini",
                provider_label="Gemini",
                litellm_id="gemini/gemini-1.5-pro",
                model_id="gemini-1.5-pro",
            ),
        ]

        with patch("backend.providers.list_providers_static", return_value={"gemini": {}}):
            with patch("backend.providers.model_discovery.fetch_models_from_provider", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = mock_models

                result = await llm._fetch_provider_models("gemini", "sk-test")

                self.assertEqual(len(result), 1)
                self.assertEqual(result[0], "gemini/gemini-1.5-pro")

    async def test_fetch_nvidia_models(self):
        """Fetches models from NVIDIA."""
        mock_models = [
            ModelInfo(
                id="nemotron-3-ultra",
                name="Nemotron 3 Ultra",
                provider_id="nvidia",
                provider_label="NVIDIA NIM",
                litellm_id="nvidia_nim/nemotron-3-ultra",
                model_id="nemotron-3-ultra",
            ),
        ]

        with patch("backend.providers.list_providers_static", return_value={"nvidia": {}}):
            with patch("backend.providers.model_discovery.fetch_models_from_provider", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = mock_models

                result = await llm._fetch_provider_models("nvidia", "sk-test")

                self.assertEqual(len(result), 1)
                self.assertEqual(result[0], "nvidia_nim/nemotron-3-ultra")

    async def test_unknown_provider_returns_empty(self):
        """Unknown provider returns empty list."""
        with patch("backend.providers.list_providers_static", return_value={}):
            result = await llm._fetch_provider_models("unknown", "sk-test")
            self.assertEqual(result, [])

    async def test_exception_returns_empty(self):
        """Exception during fetch returns empty list."""
        with patch("backend.providers.list_providers_static", return_value={"openai": {}}):
            with patch("backend.providers.model_discovery.fetch_models_from_provider", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.side_effect = Exception("Network error")

                result = await llm._fetch_provider_models("openai", "sk-test")
                self.assertEqual(result, [])

    async def test_deduplicates_by_litellm_id(self):
        """Deduplicates by litellm_id."""
        mock_models = [
            ModelInfo(
                id="gpt-4o",
                name="GPT-4o",
                provider_id="openai",
                provider_label="OpenAI",
                litellm_id="openai/gpt-4o",
                model_id="gpt-4o",
            ),
            ModelInfo(
                id="gpt-4o-2",
                name="GPT-4o v2",
                provider_id="openai",
                provider_label="OpenAI",
                litellm_id="openai/gpt-4o",  # Same litellm_id
                model_id="gpt-4o-2",
            ),
        ]

        with patch("backend.providers.list_providers_static", return_value={"openai": {}}):
            with patch("backend.providers.model_discovery.fetch_models_from_provider", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = mock_models

                result = await llm._fetch_provider_models("openai", "sk-test")
                self.assertEqual(len(result), 1)


class OllamaWrapperTests(unittest.IsolatedAsyncioTestCase):
    """Tests for Ollama backward-compatible wrapper functions."""

    async def test_list_ollama_models_calls_fetch(self):
        """list_ollama_models calls fetch_ollama_models."""
        mock_models = [
            ModelInfo(
                id="llama3.1",
                name="Llama 3.1",
                provider_id="ollama",
                provider_label="Ollama",
                litellm_id="ollama/llama3.1",
                model_id="llama3.1",
            ),
        ]

        with patch("backend.providers.model_discovery.fetch_ollama_models", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_models

            result = await llm.list_ollama_models("http://localhost:11434")

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].name, "Llama 3.1")
            mock_fetch.assert_called_once_with("http://localhost:11434")

    async def test_try_start_ollama_calls_real(self):
        """_try_start_ollama calls the real function."""
        # Mock the async function properly
        with patch("backend.providers.ollama._try_start_ollama", new_callable=AsyncMock) as mock_start:
            await llm._try_start_ollama()
            mock_start.assert_called_once()

    def test_cleanup_ollama_calls_real(self):
        """_cleanup_ollama calls the real function."""
        with patch("backend.providers.cleanup_ollama") as mock_cleanup:
            llm._cleanup_ollama()
            mock_cleanup.assert_called_once()


class GetAttrTests(unittest.TestCase):
    """Tests for __getattr__ lazy loading."""

    def test_providers_static_lazy_load(self):
        """_providers_static triggers lazy load."""
        # The __getattr__ for _providers_static imports from backend.providers.list_providers_static
        # We need to mock it properly. First delete the module-level attribute to trigger __getattr__
        import backend.llm as llm_module
        if hasattr(llm_module, '_providers_static'):
            delattr(llm_module, '_providers_static')

        with patch("backend.providers.list_providers_static", return_value={"openai": {"label": "OpenAI", "local": False, "env_key_set": False}}):
            result = llm_module._providers_static
            self.assertEqual(result, {"openai": {"label": "OpenAI", "local": False, "env_key_set": False}})

    def test_ollama_start_attempted_lazy_load(self):
        """_ollama_start_attempted triggers lazy load."""
        with patch("backend.providers.model_discovery._ollama_start_attempted", True):
            result = llm._ollama_start_attempted
            self.assertTrue(result)

    def test_ollama_process_lazy_load(self):
        """_ollama_process triggers lazy load."""
        mock_process = MagicMock()
        with patch("backend.providers.model_discovery._ollama_process", mock_process):
            result = llm._ollama_process
            self.assertEqual(result, mock_process)

    def test_unknown_attribute_raises(self):
        """Unknown attribute raises AttributeError."""
        with self.assertRaises(AttributeError) as ctx:
            _ = llm._nonexistent_attribute
        self.assertIn("nonexistent_attribute", str(ctx.exception))


class AsyncFacadeTests(unittest.IsolatedAsyncioTestCase):
    """Tests for async facade functions."""

    async def test_list_models_delegates(self):
        """list_models delegates to providers.list_models."""
        mock_models = [
            ModelInfo(id="m1", name="Model 1", provider_id="p1", provider_label="Provider 1", litellm_id="p1/m1")
        ]

        with patch("backend.providers.list_models", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = mock_models
            mock_db = MagicMock()

            result = await llm.list_models(mock_db)

            self.assertEqual(result, mock_models)
            mock_list.assert_called_once_with(mock_db)

    async def test_list_provider_status_delegates(self):
        """list_provider_status delegates to providers.list_provider_status."""
        mock_status = [{"id": "p1", "status": "connected"}]

        with patch("backend.providers.list_provider_status", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = mock_status
            mock_db = MagicMock()

            result = await llm.list_provider_status(mock_db)

            self.assertEqual(result, mock_status)
            mock_list.assert_called_once_with(mock_db)

    async def test_default_model_id_delegates(self):
        """default_model_id delegates to providers.default_model_id."""
        with patch("backend.providers.default_model_id", new_callable=AsyncMock) as mock_default:
            mock_default.return_value = "openai::openai/gpt-4o"
            mock_db = MagicMock()

            result = await llm.default_model_id(mock_db)

            self.assertEqual(result, "openai::openai/gpt-4o")
            mock_default.assert_called_once_with(mock_db)

    async def test_stream_completion_delegates(self):
        """stream_completion delegates to providers.stream_completion."""
        async def mock_generator():
            yield "chunk1"
            yield "chunk2"

        with patch("backend.providers.stream_completion", return_value=mock_generator()) as mock_stream:
            mock_db = MagicMock()

            chunks = []
            async for chunk in llm.stream_completion(
                "openai::openai/gpt-4o",
                [{"role": "user", "content": "hello"}],
                mock_db,
                temperature=0.5,
                max_tokens=512,
            ):
                chunks.append(chunk)

            self.assertEqual(chunks, ["chunk1", "chunk2"])

    async def test_get_db_keys_delegates(self):
        """get_db_keys delegates to providers.get_db_keys."""
        mock_keys = {"openai": "sk-test"}

        with patch("backend.providers.get_db_keys", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_keys
            mock_db = MagicMock()

            result = await llm.get_db_keys(mock_db)

            self.assertEqual(result, mock_keys)
            mock_get.assert_called_once_with(mock_db)

    async def test_resolve_api_key_delegates(self):
        """resolve_api_key delegates to providers.resolve_api_key."""
        with patch("backend.providers.resolve_api_key", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = "sk-resolved"
            mock_db = MagicMock()

            result = await llm.resolve_api_key("openai", mock_db)

            self.assertEqual(result, "sk-resolved")
            mock_resolve.assert_called_once_with("openai", mock_db)


class ProviderRegistryTests(unittest.TestCase):
    """Tests for provider registry and constants."""

    def test_providers_dict_exists(self):
        """PROVIDERS dict is available."""
        self.assertIsInstance(llm.PROVIDERS, dict)
        self.assertGreater(len(llm.PROVIDERS), 0)

    def test_curated_models_dict_exists(self):
        """CURATED_MODELS dict is available."""
        self.assertIsInstance(llm.CURATED_MODELS, dict)
        self.assertGreater(len(llm.CURATED_MODELS), 0)

    def test_models_dict_exists(self):
        """MODELS dict is available."""
        self.assertIsInstance(llm.MODELS, dict)

    def test_registry_exists(self):
        """ProviderRegistry instance is available."""
        self.assertIsNotNone(llm.registry)

    def test_inaccessible_models_set(self):
        """_inaccessible_models set is available."""
        self.assertIsInstance(llm._inaccessible_models, set)

    def test_inaccessible_models_alias(self):
        """inaccessible_models alias points to same set."""
        self.assertIs(llm.inaccessible_models, llm._inaccessible_models)

    def test_clear_inaccessible_models_function(self):
        """clear_inaccessible_models function exists."""
        self.assertTrue(callable(llm.clear_inaccessible_models))

    def test_list_providers_static_function(self):
        """list_providers_static function exists."""
        self.assertTrue(callable(llm.list_providers_static))
        result = llm.list_providers_static()
        self.assertIsInstance(result, dict)

    def test_fetch_ollama_models_function(self):
        """fetch_ollama_models function is available."""
        self.assertTrue(callable(llm.fetch_ollama_models))

    def test_cleanup_ollama_function(self):
        """cleanup_ollama function is available."""
        self.assertTrue(callable(llm.cleanup_ollama))


class ModelInfoTests(unittest.TestCase):
    """Tests for ModelInfo type."""

    def test_model_info_creation(self):
        """ModelInfo can be created with all fields."""
        model = ModelInfo(
            id="test::model",
            name="Test Model",
            provider_id="test",
            provider_label="Test Provider",
            litellm_id="test/model",
            model_id="model",
            description="A test model",
        )
        self.assertEqual(model.id, "test::model")
        self.assertEqual(model.name, "Test Model")
        self.assertEqual(model.provider_id, "test")
        self.assertEqual(model.provider_label, "Test Provider")
        self.assertEqual(model.litellm_id, "test/model")
        self.assertEqual(model.model_id, "model")
        self.assertEqual(model.description, "A test model")

    def test_model_info_optional_fields(self):
        """ModelInfo optional fields default to empty string."""
        model = ModelInfo(
            id="test::model",
            name="Test Model",
            provider_id="test",
            provider_label="Test Provider",
            litellm_id="test/model",
        )
        # model_id and description default to empty string
        self.assertEqual(model.model_id, "")
        self.assertEqual(model.description, "")


class ProviderConfigTests(unittest.TestCase):
    """Tests for ProviderConfig type."""

    def test_provider_config_creation(self):
        """ProviderConfig can be created with required fields."""
        config = ProviderConfig(
            provider_id="test",
            label="Test Provider",
            local=False,
            env_key_name="TEST_API_KEY",
            api_base="https://api.test.com",
            model_endpoint="https://api.test.com/models",
            auth_type="bearer",
            json_path="data",
            id_field="id",
            litellm_prefix="test/",
        )
        self.assertEqual(config.provider_id, "test")
        self.assertEqual(config.label, "Test Provider")
        self.assertFalse(config.local)
        self.assertEqual(config.env_key_name, "TEST_API_KEY")

    def test_provider_config_optional_fields(self):
        """ProviderConfig optional fields have defaults."""
        config = ProviderConfig(
            provider_id="test",
            label="Test Provider",
            local=False,
            env_key_name="TEST_API_KEY",
            api_base="https://api.test.com",
            model_endpoint="https://api.test.com/models",
            auth_type="bearer",
            json_path="data",
            id_field="id",
            litellm_prefix="test/",
        )
        self.assertEqual(config.auth_header_name, "Authorization")
        self.assertIsNone(config.extra_headers)
        self.assertIsNone(config.query_key)
        self.assertEqual(config.litellm_prefix, "test/")  # explicitly set in test
        self.assertIsNone(config.name_field)
        self.assertIsNone(config.description_field)
        self.assertEqual(config.auth_type, "bearer")
        self.assertEqual(config.json_path, "data")
        self.assertEqual(config.id_field, "id")
        self.assertEqual(config.strip_prefix, "")

    def test_provider_config_default_optional_fields(self):
        """ProviderConfig optional fields default to None when not provided."""
        config = ProviderConfig(
            provider_id="test",
            label="Test Provider",
            local=False,
            env_key_name="TEST_API_KEY",
            api_base="https://api.test.com",
            model_endpoint="https://api.test.com/models",
            auth_type="bearer",
            json_path="data",
            id_field="id",
        )
        self.assertEqual(config.auth_header_name, "Authorization")
        self.assertIsNone(config.extra_headers)
        self.assertIsNone(config.query_key)
        self.assertIsNone(config.litellm_prefix)  # defaults to None
        self.assertIsNone(config.name_field)
        self.assertIsNone(config.description_field)


class ExportsTests(unittest.TestCase):
    """Tests for __all__ exports."""

    def test_all_exports_present(self):
        """All exports in __all__ are available in module."""
        for name in llm.__all__:
            self.assertTrue(hasattr(llm, name), f"Missing export: {name}")

    def test_main_async_api_exports(self):
        """Main async API functions are exported."""
        for name in ["list_models", "list_provider_status", "default_model_id", "stream_completion", "get_db_keys", "resolve_api_key"]:
            self.assertIn(name, llm.__all__)

    def test_provider_registry_exports(self):
        """Provider registry exports are present."""
        for name in ["registry", "list_providers_static", "clear_inaccessible_models"]:
            self.assertIn(name, llm.__all__)

    def test_types_exports(self):
        """Type exports are present."""
        for name in ["ModelInfo", "ProviderConfig"]:
            self.assertIn(name, llm.__all__)

    def test_legacy_exports(self):
        """Legacy compatibility exports are present."""
        for name in ["CURATED_MODELS", "MODELS", "PROVIDERS", "_inaccessible_models", "inaccessible_models"]:
            self.assertIn(name, llm.__all__)

    def test_model_discovery_exports(self):
        """Model discovery exports are present."""
        for name in ["fetch_models_from_provider", "fetch_ollama_models", "cleanup_ollama", "_fetch_provider_models"]:
            self.assertIn(name, llm.__all__)

    def test_utilities_exports(self):
        """Utility exports are present."""
        for name in ["sanitize_error", "_cleanup_ollama", "_linked_providers"]:
            self.assertIn(name, llm.__all__)


class StreamCompletionErrorHandlingTests(unittest.IsolatedAsyncioTestCase):
    """Tests for stream_completion error handling."""

    async def test_stream_completion_propagates_exception(self):
        """Exceptions from provider are propagated."""
        async def mock_generator():
            yield "chunk1"
            raise Exception("Provider error")

        with patch("backend.providers.stream_completion", return_value=mock_generator()):
            mock_db = MagicMock()

            chunks = []
            with self.assertRaises(Exception) as ctx:
                async for chunk in llm.stream_completion(
                    "openai::openai/gpt-4o",
                    [{"role": "user", "content": "hello"}],
                    mock_db,
                ):
                    chunks.append(chunk)

            self.assertIn("Provider error", str(ctx.exception))

    async def test_stream_completion_passes_parameters(self):
        """All parameters are passed to underlying function."""
        async def mock_generator():
            yield "chunk"

        with patch("backend.providers.stream_completion", return_value=mock_generator()) as mock_stream:
            mock_db = MagicMock()

            async for _ in llm.stream_completion(
                "ollama::llama3.1",
                [{"role": "user", "content": "test"}],
                mock_db,
                temperature=0.8,
                max_tokens=2048,
                reasoning_effort="high",
            ):
                pass

            mock_stream.assert_called_once()
            # Check args - parameters passed positionally
            args, kwargs = mock_stream.call_args
            self.assertEqual(args[0], "ollama::llama3.1")  # model_id
            self.assertEqual(args[1], [{"role": "user", "content": "test"}])  # messages
            self.assertEqual(args[2], mock_db)  # db
            self.assertEqual(args[3], 0.8)  # temperature
            self.assertEqual(args[4], 2048)  # max_tokens
            self.assertEqual(args[5], "high")  # reasoning_effort


if __name__ == "__main__":
    unittest.main()


