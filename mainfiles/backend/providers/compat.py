"""
Compatibility module - exposes legacy constants from original llm.py
for backward compatibility with existing code.
"""
from .base import ModelInfo
from backend.response_events import ModelCapabilities

# Curated models - hardcoded friendly names for popular models
CURATED_MODELS: dict[str, ModelInfo] = {
    # Anthropic
    "claude-sonnet-4": ModelInfo(
        id="claude-sonnet-4", name="Claude Sonnet 4", provider_id="anthropic",
        provider_label="Anthropic", litellm_id="anthropic/claude-sonnet-4-20250514",
        capabilities=ModelCapabilities(streaming=True, tools=True, reasoning=True, vision=True, structured_output=True)
    ),
    "claude-opus-4": ModelInfo(
        id="claude-opus-4", name="Claude Opus 4", provider_id="anthropic",
        provider_label="Anthropic", litellm_id="anthropic/claude-opus-4-20250514",
        capabilities=ModelCapabilities(streaming=True, tools=True, reasoning=True, vision=True, structured_output=True)
    ),
    "claude-haiku-3": ModelInfo(
        id="claude-haiku-3", name="Claude Haiku 3.5", provider_id="anthropic",
        provider_label="Anthropic", litellm_id="anthropic/claude-3-5-haiku-20241022",
        capabilities=ModelCapabilities(streaming=True, tools=True, vision=True, structured_output=True)
    ),
    # OpenAI
    "gpt-4o": ModelInfo(
        id="gpt-4o", name="GPT-4o", provider_id="openai", provider_label="OpenAI",
        litellm_id="openai/gpt-4o",
        capabilities=ModelCapabilities(streaming=True, tools=True, vision=True, structured_output=True)
    ),
    "gpt-4o-mini": ModelInfo(
        id="gpt-4o-mini", name="GPT-4o Mini", provider_id="openai", provider_label="OpenAI",
        litellm_id="openai/gpt-4o-mini",
        capabilities=ModelCapabilities(streaming=True, tools=True, vision=True, structured_output=True)
    ),
    "o3-mini": ModelInfo(
        id="o3-mini", name="o3-mini", provider_id="openai", provider_label="OpenAI",
        litellm_id="openai/o3-mini",
        capabilities=ModelCapabilities(streaming=True, tools=True, reasoning=True, structured_output=True)
    ),
    # NVIDIA NIM
    "nim-llama-3-1-8b": ModelInfo(
        id="nim-llama-3-1-8b", name="Llama 3.1 8B", provider_id="nvidia", provider_label="NVIDIA NIM",
        litellm_id="nvidia_nim/meta/llama-3.1-8b-instruct",
        capabilities=ModelCapabilities(streaming=True, tools=True)
    ),
    "nim-llama-3-3-70b": ModelInfo(
        id="nim-llama-3-3-70b", name="Llama 3.3 70B", provider_id="nvidia", provider_label="NVIDIA NIM",
        litellm_id="nvidia_nim/meta/llama-3.3-70b-instruct",
        capabilities=ModelCapabilities(streaming=True, tools=True)
    ),
    "nim-mixtral-8x7b": ModelInfo(
        id="nim-mixtral-8x7b", name="Mixtral 8x7B", provider_id="nvidia", provider_label="NVIDIA NIM",
        litellm_id="nvidia_nim/mistralai/mixtral-8x7b-instruct-v0.1",
        capabilities=ModelCapabilities(streaming=True, tools=True)
    ),
    "nim-nemotron-ultra": ModelInfo(
        id="nim-nemotron-ultra", name="Nemotron 4 Ultra", provider_id="nvidia", provider_label="NVIDIA NIM",
        litellm_id="nvidia_nim/nvidia/nemotron-4-ultra-546b-a55b",
        capabilities=ModelCapabilities(streaming=True, tools=True)
    ),
    "nim-qwen-3-5-80b": ModelInfo(
        id="nim-qwen-3-5-80b", name="Qwen3 80B", provider_id="nvidia", provider_label="NVIDIA NIM",
        litellm_id="nvidia_nim/qwen/qwen3-next-80b-a3b-instruct",
        capabilities=ModelCapabilities(streaming=True, tools=True)
    ),
    "nim-deepseek-r1": ModelInfo(
        id="nim-deepseek-r1", name="DeepSeek R1", provider_id="nvidia", provider_label="NVIDIA NIM",
        litellm_id="nvidia_nim/deepseek-ai/deepseek-r1",
        capabilities=ModelCapabilities(streaming=True, tools=True, reasoning=True)
    ),
    # DeepSeek
    "deepseek-chat": ModelInfo(
        id="deepseek-chat", name="DeepSeek V3", provider_id="deepseek", provider_label="DeepSeek",
        litellm_id="deepseek/deepseek-chat",
        capabilities=ModelCapabilities(streaming=True, tools=True)
    ),
    # Mistral
    "mistral-large": ModelInfo(
        id="mistral-large", name="Mistral Large", provider_id="mistral", provider_label="Mistral",
        litellm_id="mistral/mistral-large-latest",
        capabilities=ModelCapabilities(streaming=True, tools=True, structured_output=True)
    ),
    # Gemini
    "gemini-2-5-pro": ModelInfo(
        id="gemini-2-5-pro", name="Gemini 2.5 Pro", provider_id="gemini", provider_label="Gemini",
        litellm_id="gemini/gemini-2.5-pro",
        capabilities=ModelCapabilities(streaming=True, tools=True, reasoning=True, vision=True, structured_output=True)
    ),
    "gemini-2-5-flash": ModelInfo(
        id="gemini-2-5-flash", name="Gemini 2.5 Flash", provider_id="gemini", provider_label="Gemini",
        litellm_id="gemini/gemini-2.5-flash",
        capabilities=ModelCapabilities(streaming=True, tools=True, vision=True, structured_output=True)
    ),
}

# MODELS dict maps app-side model IDs to ModelInfo
MODELS: dict[str, ModelInfo] = {}

# Fill MODELS from CURATED_MODELS
for model in CURATED_MODELS.values():
    MODELS[model.id] = model

# Provider metadata for settings UI
PROVIDERS = {
    "openai":     {"label": "OpenAI",     "local": False, "env_key": "OPENAI_API_KEY",     "url": "https://api.openai.com/v1/models"},
    "anthropic":  {"label": "Anthropic",  "local": False, "env_key": "ANTHROPIC_API_KEY",  "url": "https://api.anthropic.com/v1/models"},
    "nvidia":     {"label": "NVIDIA NIM", "local": False, "env_key": "NVIDIA_NIM_API_KEY", "url": "https://integrate.api.nvidia.com/v1/models"},
    "together":   {"label": "Together",   "local": False, "env_key": "TOGETHER_API_KEY",   "url": "https://api.together.xyz/v1/models"},
    "groq":       {"label": "Groq",       "local": False, "env_key": "GROQ_API_KEY",       "url": "https://api.groq.com/openai/v1/models"},
    "openrouter": {"label": "OpenRouter", "local": False, "env_key": "OPENROUTER_API_KEY", "url": "https://openrouter.ai/api/v1/models"},
    "deepseek":   {"label": "DeepSeek",   "local": False, "env_key": "DEEPSEEK_API_KEY",   "url": "https://api.deepseek.com/v1/models"},
    "mistral":    {"label": "Mistral",    "local": False, "env_key": "MISTRAL_API_KEY",    "url": "https://api.mistral.ai/v1/models"},
    "gemini":     {"label": "Gemini",     "local": False, "env_key": "GEMINI_API_KEY",     "url": "https://generativelanguage.googleapis.com/v1beta/models"},
    "ollama":     {"label": "Ollama",     "local": True,  "env_key": None,                 "url": "http://localhost:11434/api/tags"},
    "omniroute":  {"label": "OmniRoute",  "local": True,  "env_key": "OMNIROUTE_API_KEY",  "url": "http://localhost:20128/v1/models"},

}

__all__ = ["CURATED_MODELS", "MODELS", "PROVIDERS"]