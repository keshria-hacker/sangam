"""
api_routes/models_routes.py — model catalogue endpoints.
"""
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import llm
from ..database import get_db
from ..schemas import ModelInfo, ProviderModelEntry
from .common import router


def _to_model_info(model) -> ModelInfo:
    """Normalize a provider model (dataclass *or* dict) into the wire schema."""
    if isinstance(model, dict):
        return ModelInfo(
            id=model["id"],
            name=model.get("name") or model["id"],
            provider=model.get("provider") or model.get("provider_id", ""),
            litellm_id=model.get("litellm_id") or model["id"],
            context_window=model.get("context_window"),
            capabilities=model.get("capabilities"),
        )
    return ModelInfo(
        id=model.id,
        name=model.name,
        provider=getattr(model, "provider", None) or getattr(model, "provider_id", ""),
        litellm_id=getattr(model, "litellm_id", None) or model.id,
        context_window=getattr(model, "context_window", None),
        capabilities=getattr(model, "capabilities", None),
    )


@router.get("/models", response_model=list[ModelInfo])
async def get_models(db: AsyncSession = Depends(get_db)):
    """Get all selectable models from every linked provider."""
    return [_to_model_info(m) for m in await llm.list_models(db)]


@router.get("/models/{provider}", response_model=list[ProviderModelEntry])
async def get_provider_models(provider: str, db: AsyncSession = Depends(get_db)):
    """Get the selectable models that belong to one provider."""
    entries = [_to_model_info(m) for m in await llm.list_models(db)]
    return [
        ProviderModelEntry(id=m.id, name=m.name, provider=m.provider)
        for m in entries
        if m.provider == provider
    ]
