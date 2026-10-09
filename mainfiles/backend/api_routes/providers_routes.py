"""
api_routes/providers_routes.py — provider key management, live model refresh,
web search, and inaccessible-model maintenance endpoints.
"""
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .. import llm, websearch
from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..models import ProviderKey
from ..schemas import (
    ProviderKeyIn,
    ProviderKeyOut,
    ProviderModelEntry,
    ProviderStatus,
    RefreshModelsOut,
)
from .common import logger, router


@router.get("/settings/providers", response_model=list[ProviderKeyOut])
async def list_provider_keys(db: AsyncSession = Depends(get_db)):
    """Return ALL known providers with their key status and human-readable
    label. Unlike /api/providers (which only shows linked providers), this
    endpoint is used by the Settings UI to let users manage keys for any
    provider — linked or not."""
    db_keys = await llm.get_db_keys(db)
    out = []
    for pid, meta in llm.list_providers_static().items():
        if meta["local"]:
            continue
        db_key = db_keys.get(pid)
        if db_key:
            masked = f"{db_key[:6]}···{db_key[-4:]}" if len(db_key) > 10 else "···"
            out.append(ProviderKeyOut(provider_id=pid, label=meta["label"], linked=True, masked_key=masked))
        elif meta["env_key_set"]:
            out.append(ProviderKeyOut(provider_id=pid, label=meta["label"], linked=True, masked_key="(from .env)"))
        else:
            out.append(ProviderKeyOut(provider_id=pid, label=meta["label"], linked=False, masked_key=None))
    return out


@router.put("/settings/providers/{provider_id}/key", response_model=ProviderKeyOut)
async def set_provider_key(provider_id: str, payload: ProviderKeyIn, db: AsyncSession = Depends(get_db)):
    """Link a provider API key from the Settings UI (stored encrypted)."""
    static = llm.list_providers_static()
    if provider_id not in static:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider_id}")
    if static[provider_id]["local"]:
        raise HTTPException(status_code=400, detail="Local runtimes don't use an API key")

    api_key = payload.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=422, detail="API key cannot be blank")

    existing = await db.get(ProviderKey, provider_id)
    if existing:
        existing.api_key = api_key
    else:
        db.add(ProviderKey(provider_id=provider_id, api_key=api_key))
    await db.commit()

    key = api_key
    masked = f"{key[:6]}···{key[-4:]}" if len(key) > 10 else "···"
    return ProviderKeyOut(provider_id=provider_id, label=static[provider_id]["label"], linked=True, masked_key=masked)


@router.delete("/settings/providers/{provider_id}/key", status_code=204)
async def delete_provider_key(provider_id: str, db: AsyncSession = Depends(get_db)):
    """Unlink a stored provider API key."""
    static = llm.list_providers_static()
    if provider_id not in static:
        raise HTTPException(status_code=404, detail="Provider not found")
    existing = await db.get(ProviderKey, provider_id)
    if existing:
        await db.delete(existing)
        await db.commit()


@router.get("/settings/providers/{provider_id}/models/refresh", response_model=RefreshModelsOut)
async def refresh_provider_models(provider_id: str, db: AsyncSession = Depends(get_db)):
    """Live-fetch the full model catalogue for a linked provider.

    Queries the provider's model listing endpoint (e.g. ``/v1/models``) and
    returns the standardized model list with a count. Errors inside the fetch
    are caught gracefully (``success=False``), so transient network blips never
    surface as a 5xx.
    """
    config = llm.registry.get_config(provider_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    if config.local:
        raise HTTPException(status_code=400, detail="Local runtimes don't support model listing")

    api_key = await llm.resolve_api_key(provider_id, db)
    if api_key is None:
        raise HTTPException(status_code=400, detail="No API key linked")

    try:
        models = await llm.fetch_models_from_provider(
            api_key=api_key,
            endpoint_url=config.model_endpoint,
            provider_id=provider_id,
            provider_label=config.label,
            auth_type=config.auth_type,
            auth_header_name=config.auth_header_name or "x-api-key",
            query_key=config.query_key,
            json_path=config.json_path,
            id_field=config.id_field,
            strip_prefix=config.strip_prefix or "",
            extra_headers=config.extra_headers,
            timeout_seconds=20.0,
        )
        return RefreshModelsOut(
            provider_id=provider_id,
            success=True,
            count=len(models),
            models=[ProviderModelEntry(**m) for m in models],
        )
    except Exception as exc:  # noqa: BLE001 — never 5xx on a transient blip
        logger.warning("fetch_models_from_provider(%s) failed: %s", provider_id, exc)
        return RefreshModelsOut(provider_id=provider_id, success=False, count=0, models=[])


@router.get("/websearch")
async def get_websearch(q: str, max_results: int = 5):
    """Live web search. Works out of the box via DuckDuckGo (no key); upgrade
    by setting WEB_SEARCH_PROVIDER + WEB_SEARCH_API_KEY in .env."""
    if not q or not q.strip():
        raise HTTPException(status_code=422, detail="Query (q) is required")
    try:
        results = await websearch.web_search(q, max_results=max_results)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "query": q,
        "provider": (settings.WEB_SEARCH_PROVIDER or "duckduckgo"),
        "results": [
            {"title": r.title, "url": r.url, "snippet": r.snippet} for r in results
        ],
    }


@router.post("/models/inaccessible/clear", status_code=204)
async def clear_inaccessible_models():
    """Clear models flagged as inaccessible so they reappear on the next fetch."""
    llm.clear_inaccessible_models()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

from .common import public_router  # noqa: E402


@public_router.get("/health")
async def health():
    """Public liveness probe (no auth)."""
    return {"status": "ok", "app": settings.APP_NAME}


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


@router.get("/providers", response_model=list[ProviderStatus])
async def get_providers(db: AsyncSession = Depends(get_db)):
    """Return providers that are currently reachable (key linked + endpoint up)."""
    return await llm.list_provider_status(db)


# --- Phase 6.4d: fallback chain status ---
@router.get("/providers/status")
async def get_provider_status(
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    """Get circuit breaker + quota status for all providers."""
    from ..providers.fallback_chain import get_fallback_chain
    chain = get_fallback_chain()
    return {"providers": chain.get_states()}
