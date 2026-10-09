"""
config.py — centralized, typed application settings.

Everything environment-specific (API keys, database URL, upload limits)
lives here and is loaded from a `.env` file via pydantic-settings. No other
module should read `os.environ` directly — import `settings` from here instead.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent          # <root>/mainfiles
PROJECT_ROOT = BASE_DIR.parent                              # repository root

# Default workspace root is the project root (parent of backend)
DEFAULT_WORKSPACE_ROOT = BASE_DIR


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env"),  # the launcher (start.py) writes .env at the repo root
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    APP_NAME: str = "UniversalAI"
    ENV: str = "development"          # development | production
    DEBUG: bool = Field(default=False, validation_alias="APP_DEBUG")
    API_PREFIX: str = "/api"

    # --- Security ---
    MASTER_KEY: str | None = None  # Required for API key encryption at rest (Fernet key)

    # --- CORS ---
    ALLOWED_ORIGINS: list[str] = ["http://localhost:5500", "http://127.0.0.1:5500", "http://localhost:3000"]

    # --- Database ---
    DATABASE_URL: str = Field(
        default=f"sqlite+aiosqlite:///{BASE_DIR.as_posix()}/history/sangam.db",
        description="Database URL — override with env var (e.g. sqlite+aiosqlite:// for in-memory testing)",
    )

    # --- Storage ---
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    MAX_UPLOAD_SIZE_MB: int = 25
    ALLOWED_UPLOAD_EXTENSIONS: set[str] = {
        "pdf", "docx", "txt", "csv", "xlsx", "pptx", "json", "html", "xml",
        "py", "java", "js", "c", "cpp", "cs", "go", "rs", "php", "sql", "r", "md",
    }

    # --- Workspace ---
    # Workspace root for file system operations (list_files, read_file, execute_code)
    # Defaults to project root. Can be overridden via WORKSPACE_ROOT env var.
    WORKSPACE_ROOT: Path = DEFAULT_WORKSPACE_ROOT

    # --- Default generation parameters ---
    # DEFAULT_MODEL is intentionally unused — see llm.default_model_id() which
    # picks the first *actually-available* model (Ollama preferred, then cloud)
    # so the app never defaults to a model whose API key isn't linked.
    DEFAULT_MODEL: str = ""
    DEFAULT_TEMPERATURE: float = 0.7
    DEFAULT_MAX_TOKENS: int = 1024

    # --- Provider API keys (only the ones you actually use need to be set) ---
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    NVIDIA_NIM_API_KEY: str | None = None
    NVIDIA_API_KEY: str | None = None
    NVIDIA_NIM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    TOGETHER_API_KEY: str | None = None
    GROQ_API_KEY: str | None = None
    OPENROUTER_API_KEY: str | None = None
    DEEPSEEK_API_KEY: str | None = None
    MISTRAL_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None

    # --- Local runtimes (no key needed, just a reachable base URL) ---
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    LM_STUDIO_BASE_URL: str = "http://localhost:1234/v1"
    VLLM_BASE_URL: str = "http://localhost:8001/v1"

    # --- OpenAI-compatible custom providers ---
    OMNIROUTE_API_KEY: str | None = None
    OMNIROUTE_BASE_URL: str = "http://localhost:20128/v1"

    # --- Redis (optional — used for distributed rate limiting) ---
    REDIS_URL: str | None = Field(
        default=None,
        description="redis[s]://... URL for distributed rate limiting. Falls back to in-memory when unset.",
    )

    # --- Web search (optional) ---
    # Free, key-less search via DuckDuckGo works out of the box. Set a provider
    # key to upgrade quality: WEB_SEARCH_PROVIDER = "tavily"|"brave" and the
    # matching WEB_SEARCH_API_KEY. Leave blank to use the built-in fallback.
    WEB_SEARCH_PROVIDER: str | None = None
    WEB_SEARCH_API_KEY: str | None = None
    WEB_SEARCH_MAX_RESULTS: int = 5

    # --- Feature flags (foundation for upcoming integrations) ---
    # Each flag gates a capability end-to-end (backend + UI). Override via env,
    # e.g. FEATURE_VOICE=true. The GET /api/features endpoint exposes them.
    FEATURE_VOICE: bool = False          # VoiceStudio-style local TTS/STT
    FEATURE_IMAGE_GEN: bool = False      # Fooocus-style local image generation
    FEATURE_MCP: bool = True             # MCP client: consume external MCP servers
    FEATURE_MULTI_AGENT: bool = False    # munder-difflin/orca-style agent teams
    FEATURE_ANALYTICS: bool = False      # openpanel-style opt-in analytics
    FEATURE_SPEC_KIT: bool = False       # spec-kit style spec-driven workflows

    # --- MCP servers (JSON list, e.g. '[{"name":"codebase","command":["codebase-memory-mcp"]}]') ---
    MCP_SERVERS_JSON: str | None = Field(
        default=None,
        description="JSON list of MCP server configs: {name, command|url, args, env}",
    )

    # --- Voice (TTS/STT) ---
    # Engines: "auto" picks the first available; "kokoro" / "faster-whisper" /
    # "openai" force one; "none" disables that direction explicitly.
    VOICE_TTS_ENGINE: str = "auto"
    VOICE_STT_ENGINE: str = "auto"
    # OpenAI-compatible audio server (OpenAI, a local VoiceStudio backend via
    # its /v1/audio/* endpoints, speaches, ...). Used when engine == "openai".
    VOICE_OPENAI_BASE_URL: str | None = None
    VOICE_OPENAI_API_KEY: str | None = None
    VOICE_OPENAI_TTS_MODEL: str = "tts-1"
    VOICE_OPENAI_STT_MODEL: str = "whisper-1"
    VOICE_KOKORO_VOICE: str = "af_heart"   # default kokoro voice id
    VOICE_WHISPER_MODEL: str = "tiny"       # faster-whisper model size
    VOICE_MAX_TTS_CHARS: int = 2000         # per-request TTS cap

    # --- API ---
    API_VERSION: str = "v1"

    def feature_flags(self) -> dict[str, bool]:
        return {
            "voice": self.FEATURE_VOICE,
            "image_gen": self.FEATURE_IMAGE_GEN,
            "mcp": self.FEATURE_MCP,
            "multi_agent": self.FEATURE_MULTI_AGENT,
            "analytics": self.FEATURE_ANALYTICS,
            "spec_kit": self.FEATURE_SPEC_KIT,
        }

    def mcp_server_configs(self) -> list[dict]:
        """Parse MCP_SERVERS_JSON into a list of server config dicts."""
        if not self.MCP_SERVERS_JSON:
            return []
        import json

        try:
            parsed = json.loads(self.MCP_SERVERS_JSON)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is only parsed once per process."""
    return Settings()


def reset_settings() -> None:
    """Clear the settings cache for testing."""
    get_settings.cache_clear()


settings = get_settings()
