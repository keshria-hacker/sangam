"""
api_routes/features_routes.py — feature flag discovery endpoint.

Each flag gates an upcoming integration end-to-end (backend + UI) and is
overridable via env, e.g. FEATURE_VOICE=true. The frontend reads this once
at startup to show/hide capability UI.
"""
from ..config import settings
from .common import router


@router.get("/features")
async def get_features():
    """Return the API version and the current feature flag map."""
    return {"version": settings.API_VERSION, "features": settings.feature_flags()}
