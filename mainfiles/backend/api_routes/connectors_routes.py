"""
api_routes/connectors_routes.py — Phase 5: OAuth connector framework API.

GET  /connectors — definitions + connected status + configured flag
GET  /connectors/{name}/authorize — authorize URL (or 422 unconfigured)
GET  /connectors/{name}/callback — exchange code for a token, store encrypted
DELETE /connectors/{name} — disconnect (delete the stored token)

The callback's redirect_uri must match the one used at authorize
time; the frontend passes it as a query param, and the server builds
the same value from the request's own base URL when absent.
"""
import json

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..connectors import authorize_url, get_registry, make_state, verify_state
from ..database import get_db
from ..models import ProviderKey
from .common import router


@router.get("/connectors")
async def list_connectors(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    rows = (await db.execute(select(ProviderKey))).scalars().all()
    connected = {r.provider_id for r in rows}
    return {
        "connectors": [
            {
                "name": d.name, "label": d.label, "scopes": d.scopes,
                "configured": d.configured,
                "connected": f"oauth:{d.name}" in connected,
            }
            for d in get_registry().values()
        ]
    }


@router.get("/connectors/{name}/authorize")
async def connector_authorize(name: str, request: Request, user=Depends(get_current_user)):
    definition = get_registry().get(name)
    if not definition:
        raise HTTPException(status_code=404, detail="Connector not found")
    if not definition.configured:
        raise HTTPException(
            status_code=422,
            detail=f"Connector {name} is not configured: set {definition.client_id_env} and {definition.client_secret_env}",
        )
    redirect_uri = str(request.base_url).rstrip("/") + f"/api/connectors/{name}/callback"
    state = make_state(name, user.id)
    return {"authorize_url": authorize_url(definition, redirect_uri, state), "state": state}


@router.get("/connectors/{name}/callback")
async def connector_callback(name: str, code: str, state: str, request: Request,
                             db: AsyncSession = Depends(get_db)):
    """OAuth callback. Authenticated by the signed state token, not by
    a session cookie — the provider redirects here from outside."""
    verified = verify_state(state)
    if not verified:
        raise HTTPException(status_code=403, detail="Invalid or expired state")
    connector_name, _user_id = verified
    if connector_name != name:
        raise HTTPException(status_code=403, detail="State does not match connector")
    definition = get_registry().get(name)
    if not definition or not definition.configured:
        raise HTTPException(status_code=422, detail="Connector not configured")
    redirect_uri = str(request.base_url).rstrip("/") + f"/api/connectors/{name}/callback"
    import httpx

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0)) as client:
            resp = await client.post(
                definition.token_url,
                data={
                    "client_id": definition.client_id,
                    "client_secret": definition.client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Token exchange failed") from None
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Token exchange failed")
    token_data = resp.json()
    access = token_data.get("access_token")
    if not access:
        raise HTTPException(status_code=502, detail="Token exchange returned no access token")
    stored = json.dumps({
        "access_token": access,
        "refresh_token": token_data.get("refresh_token"),
        "expires_at": token_data.get("expires_in"),
        "token_type": token_data.get("token_type", "Bearer"),
    })
    row = await db.get(ProviderKey, f"oauth:{name}")
    if row is None:
        row = ProviderKey(provider_id=f"oauth:{name}")
        db.add(row)
    row.api_key = stored  # hybrid property encrypts at rest
    await db.commit()
    return {"connected": True, "connector": name}


@router.delete("/connectors/{name}")
async def disconnect_connector(name: str, db: AsyncSession = Depends(get_db),
                               user=Depends(get_current_user)):
    row = await db.get(ProviderKey, f"oauth:{name}")
    if not row:
        raise HTTPException(status_code=404, detail="Connector not connected")
    await db.delete(row)
    await db.commit()
    return {"ok": True, "connector": name}
