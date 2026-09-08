"""
Provider registry - central configuration and discovery.
"""
from .base import BaseProvider, ProviderConfig


class ProviderRegistry:
    """Singleton registry of all known providers and their configurations."""

    _instance: "ProviderRegistry | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._providers: dict[str, ProviderConfig] = {}
        self._provider_classes: dict[str, type[BaseProvider]] = {}
        self._initialized = True

    def register(self, config: ProviderConfig, provider_class: type[BaseProvider] | None = None) -> None:
        """Register a provider configuration and optional custom class."""
        self._providers[config.provider_id] = config
        if provider_class:
            self._provider_classes[config.provider_id] = provider_class

    def get_config(self, provider_id: str) -> ProviderConfig | None:
        """Get provider configuration by ID."""
        return self._providers.get(provider_id)

    def get_all_configs(self) -> dict[str, ProviderConfig]:
        """Get all provider configurations."""
        return self._providers.copy()

    def get_provider_class(self, provider_id: str) -> type[BaseProvider] | None:
        """Get custom provider class if registered."""
        return self._provider_classes.get(provider_id)

    def all_provider_ids(self) -> list[str]:
        """Get list of all registered provider IDs."""
        return list(self._providers.keys())

    def all_non_local_ids(self) -> list[str]:
        """Get list of all cloud (non-local) provider IDs."""
        return [pid for pid, cfg in self._providers.items() if not cfg.local]


# Global registry instance
registry = ProviderRegistry()


# ---------- Static provider configurations ----------
# These are registered on module import

# Import settings lazily to avoid circular imports
def _get_settings():
    from config import settings
    return settings


# These will be registered by the init_provider_registry() function
# called from the facade module on first use
_STATIC_PROVIDER_CONFIGS: list[ProviderConfig] = [
    ProviderConfig(
        provider_id="openai",
        label="OpenAI",
        local=False,
        env_key_name="OPENAI_API_KEY",
        api_base="https://api.openai.com/v1",
        model_endpoint="https://api.openai.com/v1/models",
        auth_type="bearer",
        json_path="data",
        id_field="id",
        litellm_prefix="openai/",
    ),
    ProviderConfig(
        provider_id="anthropic",
        label="Anthropic",
        local=False,
        env_key_name="ANTHROPIC_API_KEY",
        api_base="https://api.anthropic.com/v1",
        model_endpoint="https://api.anthropic.com/v1/models",
        auth_type="header",
        auth_header_name="x-api-key",
        extra_headers={"anthropic-version": "2023-06-01"},
        json_path="data",
        id_field="id",
        litellm_prefix="anthropic/",
    ),
    ProviderConfig(
        provider_id="nvidia",
        label="NVIDIA NIM",
        local=False,
        env_key_name="NVIDIA_NIM_API_KEY",
        api_base="https://integrate.api.nvidia.com/v1",
        model_endpoint="https://integrate.api.nvidia.com/v1/models",
        auth_type="bearer",
        json_path="data",
        id_field="id",
        litellm_prefix="nvidia_nim/",
    ),
    ProviderConfig(
        provider_id="together",
        label="Together AI",
        local=False,
        env_key_name="TOGETHER_API_KEY",
        api_base="https://api.together.xyz/v1",
        model_endpoint="https://api.together.xyz/v1/models",
        auth_type="bearer",
        json_path="data",
        id_field="id",
        litellm_prefix="together_ai/",
    ),
    ProviderConfig(
        provider_id="groq",
        label="Groq",
        local=False,
        env_key_name="GROQ_API_KEY",
        api_base="https://api.groq.com/openai/v1",
        model_endpoint="https://api.groq.com/openai/v1/models",
        auth_type="bearer",
        json_path="data",
        id_field="id",
        litellm_prefix="groq/",
    ),
    ProviderConfig(
        provider_id="openrouter",
        label="OpenRouter",
        local=False,
        env_key_name="OPENROUTER_API_KEY",
        api_base="https://openrouter.ai/api/v1",
        model_endpoint="https://openrouter.ai/api/v1/models",
        auth_type="bearer",
        json_path="data",
        id_field="id",
        litellm_prefix="openrouter/",
    ),
    ProviderConfig(
        provider_id="deepseek",
        label="DeepSeek",
        local=False,
        env_key_name="DEEPSEEK_API_KEY",
        api_base="https://api.deepseek.com/v1",
        model_endpoint="https://api.deepseek.com/v1/models",
        auth_type="bearer",
        json_path="data",
        id_field="id",
        litellm_prefix="deepseek/",
    ),
    ProviderConfig(
        provider_id="mistral",
        label="Mistral",
        local=False,
        env_key_name="MISTRAL_API_KEY",
        api_base="https://api.mistral.ai/v1",
        model_endpoint="https://api.mistral.ai/v1/models",
        auth_type="bearer",
        json_path="data",
        id_field="id",
        litellm_prefix="mistral/",
    ),
    ProviderConfig(
        provider_id="gemini",
        label="Gemini",
        local=False,
        env_key_name="GEMINI_API_KEY",
        api_base="https://generativelanguage.googleapis.com/v1beta",
        model_endpoint="https://generativelanguage.googleapis.com/v1beta/models",
        auth_type="query",
        query_key="key",
        json_path="models",
        id_field="name",
        strip_prefix="models/",
        litellm_prefix="gemini/",
    ),
    ProviderConfig(
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
    ),
    ProviderConfig(
        provider_id="omniroute",
        label="OmniRoute",
        local=True,
        env_key_name="OMNIROUTE_API_KEY",
        api_base="http://localhost:20128/v1",
        model_endpoint="http://localhost:20128/v1/models",
        auth_type="bearer",
        json_path="data",
        id_field="id",
        litellm_prefix="openai/",
    ),
]


def init_provider_registry() -> None:
    """Initialize the registry with all static configurations."""
    for config in _STATIC_PROVIDER_CONFIGS:
        registry.register(config)