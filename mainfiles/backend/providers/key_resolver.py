"""
API key resolution - environment variables and database keys.
"""

from backend.models import ProviderKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db_keys(db: AsyncSession) -> dict[str, str]:
    """Fetch all stored provider keys from the database."""
    result = await db.execute(select(ProviderKey))
    return {record.provider_id: record.api_key for record in result.scalars()}


async def resolve_api_key(provider_id: str, db: AsyncSession) -> str | None:
    """Resolve the API key for a provider: DB first, then environment."""
    keys = await get_db_keys(db)
    key = keys.get(provider_id)
    if key and key.strip():
        return key.strip()

    # Fallback to environment
    config = get_static_env_key(provider_id)
    return config.strip() if config and config.strip() else None


def get_static_env_key(provider_id: str) -> str | None:
    """Get the environment variable key for a provider by ID."""
    from backend.config import settings

    env_map = {
        "openai": settings.OPENAI_API_KEY,
        "anthropic": settings.ANTHROPIC_API_KEY,
        "nvidia": settings.NVIDIA_NIM_API_KEY or settings.NVIDIA_API_KEY,
        "together": settings.TOGETHER_API_KEY,
        "groq": settings.GROQ_API_KEY,
        "openrouter": settings.OPENROUTER_API_KEY,
        "deepseek": settings.DEEPSEEK_API_KEY,
        "mistral": settings.MISTRAL_API_KEY,
        "gemini": settings.GEMINI_API_KEY,
        "omniroute": settings.OMNIROUTE_API_KEY,
    }
    return env_map.get(provider_id)


async def list_linked_providers(db: AsyncSession) -> set[str]:
    """Return set of provider IDs that have keys available (DB or env)."""
    db_keys = await get_db_keys(db)
    linked = set()

    for provider_id in db_keys:
        linked.add(provider_id)

    # Also check env
    for provider_id in [
        "openai", "anthropic", "nvidia", "together", "groq",
        "openrouter", "deepseek", "mistral", "gemini", "omniroute"
    ]:
        if get_static_env_key(provider_id):
            linked.add(provider_id)

    return linked