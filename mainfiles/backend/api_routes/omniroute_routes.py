"""
api_routes/omniroute_routes.py — Sangam-native OmniRoute management.

OmniRoute is a self-hosted AI gateway (or cloud) that aggregates 290+
providers behind one OpenAI-compatible endpoint. Sangam uses it to
auto-discover LLMs: once configured here, its models appear in the model
selector automatically. This is Sangam's own UI/API — not OmniRoute's
dashboard.
"""
from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import llm
from ..database import get_db
from ..models import ProviderKey
from ..providers.model_discovery import fetch_models_from_provider
from ..omniroute_config import (
    DEFAULT_CLOUD_ENDPOINT,
    DEFAULT_LOCAL_ENDPOINT,
    get_endpoint,
    set_endpoint,
)
from .common import router


class OmniRouteConfigIn(BaseModel):
    endpoint: str | None = None
    api_key: str | None = None


class OmniRouteStatusOut(BaseModel):
    endpoint: str
    has_key: bool
    reachable: bool
    model_count: int
    is_default_local: bool


def _get_key(db_key: ProviderKey | None) -> str | None:
    if db_key:
        from ..security import decrypt_field
        try:
            return decrypt_field(db_key.api_key_encrypted)
        except Exception:
            return None
    return None


@router.get("/omniroute/status", response_model=OmniRouteStatusOut)
async def omniroute_status(db: AsyncSession = Depends(get_db)):
    """Return OmniRoute configuration + reachability + model count."""
    endpoint = get_endpoint()
    db_key = await db.get(ProviderKey, "omniroute")
    has_key = _get_key(db_key) is not None

    reachable = False
    model_count = 0
    if has_key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
                r = await client.get(
                    f"{endpoint}/models",
                    headers={"Authorization": f"Bearer {_get_key(db_key)}"},
                )
                if r.status_code == 200:
                    reachable = True
                    data = r.json()
                    models = data.get("data", []) if isinstance(data, dict) else []
                    model_count = len(models) if isinstance(models, list) else 0
        except Exception:
            pass

    return OmniRouteStatusOut(
        endpoint=endpoint,
        has_key=has_key,
        reachable=reachable,
        model_count=model_count,
        is_default_local=endpoint == DEFAULT_LOCAL_ENDPOINT,
    )


@router.post("/omniroute/config", response_model=OmniRouteStatusOut)
async def omniroute_config(payload: OmniRouteConfigIn, db: AsyncSession = Depends(get_db)):
    """Set the OmniRoute endpoint and/or API key (Sangam-native, stored locally)."""
    if payload.endpoint:
        try:
            set_endpoint(payload.endpoint)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.api_key:
        from ..security import encrypt_field
        existing = await db.get(ProviderKey, "omniroute")
        enc = encrypt_field(payload.api_key.strip())
        if existing:
            existing.api_key_encrypted = enc
        else:
            db.add(ProviderKey(provider_id="omniroute", api_key_encrypted=enc))
        await db.commit()
    return await omniroute_status(db)


@router.post("/omniroute/sync")
async def omniroute_sync(db: AsyncSession = Depends(get_db)):
    """Force a model sync from OmniRoute; returns the discovered models."""
    config = llm.registry.get_config("omniroute")
    if config is None:
        raise HTTPException(status_code=404, detail="OmniRoute provider not registered")
    db_key = await db.get(ProviderKey, "omniroute")
    api_key = _get_key(db_key)
    if not api_key:
        raise HTTPException(status_code=400, detail="No OmniRoute API key saved")
    try:
        models = await fetch_models_from_provider(api_key, config)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Sync failed: {exc}") from exc
    return {
        "count": len(models),
        "models": [{"id": m.id, "name": m.name} for m in models[:100]],
    }
