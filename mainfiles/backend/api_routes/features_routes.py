"""
api_routes/features_routes.py — feature flag discovery + runtime toggles.

GET /features returns the effective flag map (env defaults + runtime overrides).
POST /features/{name} toggles a flag at runtime and persists it, so the user
can enable/disable capabilities from the Settings UI without restarting.
"""
from fastapi import HTTPException
from pydantic import BaseModel

from .. import feature_flags as ff
from ..config import settings
from .common import router


class FeatureToggle(BaseModel):
    enabled: bool


@router.get("/features")
async def get_features():
    """Return the API version and the current effective feature flag map."""
    return {
        "version": settings.API_VERSION,
        "features": ff.effective_flags(),
        "overrides": ff.get_overrides(),
    }


@router.post("/features/{name}")
async def set_feature(name: str, body: FeatureToggle):
    """Enable/disable a feature flag at runtime (persisted)."""
    name = name.lower()
    if name not in ff.KNOWN_FLAGS:
        raise HTTPException(status_code=404, detail=f"Unknown feature flag: {name}")
    ff.set_override(name, body.enabled)
    return {"name": name, "enabled": ff.is_enabled(name), "features": ff.effective_flags()}
