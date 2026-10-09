"""
api_routes/settings_routes.py — typed user settings (Phase 2 studio shell).

Generic key-value settings backed by user_preferences.settings_json.
The frontend's settings_schema.js is the source of truth for keys/defaults.
"""
import json

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import UserPreference
from .common import router


class SettingsIn(BaseModel):
    settings: dict


@router.get("/user/settings")
async def get_user_settings(db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    """Return the user's settings blob (empty dict if unset)."""
    pref = await db.get(UserPreference, user.id)
    if not pref or not pref.settings_json:
        return {"settings": {}}
    try:
        return {"settings": json.loads(pref.settings_json)}
    except (ValueError, TypeError):
        return {"settings": {}}


@router.put("/user/settings")
async def put_user_settings(payload: SettingsIn, db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    """Replace the user's settings blob (validated client-side against the schema)."""
    if not isinstance(payload.settings, dict):
        raise HTTPException(status_code=422, detail="settings must be an object")
    # Cap size to avoid abuse
    blob = json.dumps(payload.settings)
    if len(blob) > 100_000:
        raise HTTPException(status_code=422, detail="settings too large")
    pref = await db.get(UserPreference, user.id)
    if pref is None:
        pref = UserPreference(user_id=user.id)
        db.add(pref)
    pref.settings_json = blob
    await db.commit()
    return {"ok": True}
