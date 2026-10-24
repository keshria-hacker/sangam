"""api_routes/devices_routes.py — Batch 6: LAN device pairing + management.

Host routes live on the shared router (main.py mounts it behind
get_current_user, so the host session — or a device token — is
required). The claim endpoint lives on the public router: the pairing
code IS the credential there, and it is rate-limited (5 wrong codes per
client IP → 15-minute lockout, mirroring the login lockout).

  POST   /devices/pairing/start            host; LAN_ENABLED must be on
  GET    /devices/pairing                  host; pending/approved list (codes included — host only)
  GET    /devices/pairing/{pairing_id}     host; status
  POST   /devices/pairing/{pairing_id}/approve  host
  POST   /devices/pairing/{pairing_id}/deny     host
  POST   /devices/pairing/claim            public; {code} -> {token, ...} exactly once
  GET    /devices                        host; paired devices (never hashes/tokens)
  DELETE /devices/{device_id}            host; revoke one device
  POST   /devices/revoke-all             host; revoke all devices
  GET    /devices/lan                    host; LAN IPs + binding hints
  GET    /devices/cert                   host; cert fingerprint / existence
  POST   /devices/cert/regenerate        host; new cert + revoke-all + expire pairings

Error honesty for claim (unauthenticated callers must not learn whether
a code exists): unknown/denied/expired/consumed codes all return the
same generic failure, EXCEPT a correct-but-still-pending code, which
returns "waiting for host approval" — the phone needs that distinction
to keep waiting instead of giving up.
"""
from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import _hash_token, _issue_token, get_current_user
from ..database import get_db
from ..lan_pairing import (
    CLAIM_FAIL_LIMIT,
    CLAIM_FAIL_WINDOW_S,
    DEVICE_TOKEN_TTL,
    PAIRING_START_LIMIT,
    PAIRING_START_WINDOW_S,
    PAIRINGS,
    PairedDevice,
    PendingPairing,
    Pairing,
    as_aware,
    cert_info,
    create_pairing,
    expire_all_pairings,
    find_pairing_by_code,
    generate_cert,
    lan_ipv4_addresses,
)
from ..models import UserPreference
from ..ratelimit_redis import get_rate_limit_store
from .common import public_router, router

_GENERIC_CLAIM_FAILURE = "invalid or expired code"


class PairingStartIn(BaseModel):
    device_name: str | None = None


class ClaimIn(BaseModel):
    code: str


async def _lan_enabled(db: AsyncSession, user_id: str) -> bool:
    """LAN mode is opt-in and off by default; the toggle lives in the
    user's settings blob (key LAN_ENABLED, see settings_schema.js)."""
    pref = await db.get(UserPreference, user_id)
    if not pref or not pref.settings_json:
        return False
    try:
        return bool(json.loads(pref.settings_json).get("LAN_ENABLED"))
    except (ValueError, TypeError):
        return False


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


async def _persist_pairing(db: AsyncSession, pairing: Pairing) -> None:
    """Write a pairing's status back to its DB row (upsert). A row is
    only created when the code digits are known — a pairing hydrated
    from the DB after a restart has code=None and its row already
    exists, so only its status/expiry are updated."""
    row = await db.get(PendingPairing, pairing.pairing_id)
    if row is None:
        if pairing.code is None:
            return
        row = PendingPairing(
            pairing_id=pairing.pairing_id,
            user_id=pairing.user_id,
            device_name=pairing.device_name,
            code_hash=_hash_token(pairing.code),
            status=pairing.status,
            created_at=pairing.created_at,
            expires_at=pairing.expires_at,
        )
        db.add(row)
    else:
        row.status = pairing.status
        row.device_name = pairing.device_name
        row.expires_at = pairing.expires_at
    await db.commit()


async def _hydrate_pairing(db: AsyncSession, pairing_id: str, user_id: str) -> Pairing | None:
    """Load one pairing from its DB row into the in-memory cache.
    Returns None when there is no row or it belongs to another user.
    The hydrated pairing has code=None (hash-only storage); it can
    still be approved/denied, and a claim rehydrates it with the
    presented code."""
    row = await db.get(PendingPairing, pairing_id)
    if row is None or row.user_id != user_id:
        return None
    pairing = Pairing.from_row(row)
    pairing.sweep()
    if pairing.status != row.status:
        row.status = pairing.status
        await db.commit()
    PAIRINGS[pairing.pairing_id] = pairing
    return pairing


async def _hydrate_pairings_for_user(db: AsyncSession, user_id: str) -> None:
    """Hydrate every DB pairing for this user that is not already in
    memory (the restart path). In-memory pairings are authoritative and
    are never overwritten by their rows."""
    result = await db.execute(
        select(PendingPairing).where(PendingPairing.user_id == user_id)
    )
    for row in result.scalars().all():
        if row.pairing_id in PAIRINGS:
            continue
        pairing = Pairing.from_row(row)
        pairing.sweep()
        if pairing.status != row.status:
            row.status = pairing.status
        PAIRINGS[pairing.pairing_id] = pairing
    await db.commit()


async def _get_pairing(db: AsyncSession, pairing_id: str, user_id: str) -> Pairing:
    """Host lookup: in-memory first (authoritative while present), DB
    hydration on a miss (the post-restart case)."""
    pairing = PAIRINGS.get(pairing_id)
    if pairing is not None:
        if pairing.user_id != user_id:
            raise HTTPException(status_code=404, detail="Pairing not found")
        pairing.sweep()
        if pairing.status == "expired":
            await _persist_pairing(db, pairing)
        return pairing
    pairing = await _hydrate_pairing(db, pairing_id, user_id)
    if pairing is None:
        raise HTTPException(status_code=404, detail="Pairing not found")
    return pairing


async def _find_pairing_for_claim(db: AsyncSession, code: str) -> Pairing | None:
    """Claim lookup: in-memory first (preserves live expiry/approval
    state), then a DB lookup by code hash (the post-restart case, where
    the presented code rehydrates the pairing with its digits)."""
    pairing = find_pairing_by_code(code)
    if pairing is not None:
        return pairing
    row = await db.scalar(
        select(PendingPairing).where(PendingPairing.code_hash == _hash_token(code))
    )
    if row is None:
        return None
    pairing = Pairing.from_row(row, code=code)
    pairing.sweep()
    PAIRINGS[pairing.pairing_id] = pairing
    if pairing.status == "expired":
        await _persist_pairing(db, pairing)
    return pairing


def _lan_url(request: Request) -> str:
    """First detected LAN IP + the port the API was reached on (8001
    fallback). Scheme is http: serving TLS requires restarting uvicorn
    with the generated cert (see the Devices UI note), which this
    process cannot know about — so the URL never claims https it is not
    serving."""
    ips = lan_ipv4_addresses()
    port = request.url.port or 8001
    host = ips[0] if ips else "127.0.0.1"
    return f"http://{host}:{port}"


# ---------------------------------------------------------------------------
# Pairing lifecycle (host)
# ---------------------------------------------------------------------------

@router.post("/devices/pairing/start")
async def start_pairing(
    payload: PairingStartIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    if not await _lan_enabled(db, user.id):
        raise HTTPException(
            status_code=403,
            detail="LAN mode is off. Turn it on in Settings → Devices first.",
        )
    store = await get_rate_limit_store()
    allowed, _ = await store.check_limit(
        f"device_pairing_start:{user.id}", PAIRING_START_LIMIT, PAIRING_START_WINDOW_S
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many pairings started. Try again in a few minutes.",
        )
    pairing = create_pairing(user.id, (payload.device_name or "Phone").strip() or "Phone")
    # The in-memory uniqueness check in create_pairing cannot see codes
    # created before a restart (in-memory cache empty, rows still live):
    # regenerate while the new code's hash collides with a live DB row.
    result = await db.execute(
        select(PendingPairing).where(
            PendingPairing.user_id == user.id,
            PendingPairing.status.in_(["pending", "approved"]),
        )
    )
    now = datetime.now(UTC)
    live_hashes = {
        row.code_hash
        for row in result.scalars().all()
        if as_aware(row.expires_at) is None or as_aware(row.expires_at) > now
    }
    while _hash_token(pairing.code) in live_hashes:
        pairing.code = f"{secrets.randbelow(900000) + 100000:06d}"
    await _persist_pairing(db, pairing)
    fingerprint = cert_info()["fingerprint_sha256"] or ""
    lan_url = _lan_url(request)
    qr_payload = json.dumps(
        {"url": lan_url, "code": pairing.code, "fingerprint": fingerprint},
        separators=(",", ":"),
    )
    return {
        "pairing_id": pairing.pairing_id,
        "code": pairing.code,
        "device_name": pairing.device_name,
        "status": pairing.status,
        "expires_at": pairing.expires_at.isoformat(),
        "lan_url": lan_url,
        "payload": qr_payload,
    }


@router.get("/devices/pairing")
async def list_pairings(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    # Hydrate first: after a restart the pending pairings live only in
    # the DB until this call. Hydrated rows have code=None (hash-only
    # storage) — the host sees the pairing and can approve it, but the
    # digits are not recoverable from the DB.
    await _hydrate_pairings_for_user(db, user.id)
    out = []
    for pairing in sorted(PAIRINGS.values(), key=lambda p: p.created_at, reverse=True):
        if pairing.user_id != user.id:
            continue
        pairing.sweep()
        row = pairing.public()
        row["code"] = pairing.code  # host-only endpoint: the host shows its own codes
        out.append(row)
    return {"pairings": out}


@router.get("/devices/pairing/{pairing_id}")
async def pairing_status(pairing_id: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return (await _get_pairing(db, pairing_id, user.id)).public()


@router.post("/devices/pairing/{pairing_id}/approve")
async def approve_pairing(pairing_id: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    pairing = await _get_pairing(db, pairing_id, user.id)
    if pairing.status != "pending":
        raise HTTPException(status_code=409, detail=f"Pairing is no longer pending (status: {pairing.status})")
    pairing.status = "approved"
    await _persist_pairing(db, pairing)
    return pairing.public()


@router.post("/devices/pairing/{pairing_id}/deny")
async def deny_pairing(pairing_id: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    pairing = await _get_pairing(db, pairing_id, user.id)
    if pairing.status != "pending":
        raise HTTPException(status_code=409, detail=f"Pairing is no longer pending (status: {pairing.status})")
    pairing.status = "denied"
    await _persist_pairing(db, pairing)
    return pairing.public()


# ---------------------------------------------------------------------------
# Claim (public — the code is the credential; rate-limited)
# ---------------------------------------------------------------------------

@public_router.post("/devices/pairing/claim")
async def claim_pairing(payload: ClaimIn, request: Request, db: AsyncSession = Depends(get_db)):
    store = await get_rate_limit_store()
    allowed, _ = await store.check_limit(
        f"device_claim_fail:{_client_ip(request)}", CLAIM_FAIL_LIMIT, CLAIM_FAIL_WINDOW_S
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many incorrect pairing codes. Try again later.",
        )
    code = (payload.code or "").strip()
    pairing = await _find_pairing_for_claim(db, code) if code else None
    if pairing is None:
        raise HTTPException(status_code=404, detail=_GENERIC_CLAIM_FAILURE)
    if pairing.status == "pending":
        # Correct code, host has not approved yet: the phone keeps waiting.
        raise HTTPException(status_code=403, detail="waiting for host approval")
    if pairing.status != "approved":
        # denied / expired / claimed: same generic failure, no leak.
        # Persist a sweep-to-expired so a restarted process agrees.
        if pairing.status == "expired":
            await _persist_pairing(db, pairing)
        raise HTTPException(status_code=404, detail=_GENERIC_CLAIM_FAILURE)
    # Approved + unclaimed + unexpired: consume exactly once.
    pairing.status = "claimed"
    await _persist_pairing(db, pairing)
    token = _issue_token()
    now = datetime.now(UTC)
    device = PairedDevice(
        id=f"dev-{secrets.token_hex(8)}",
        user_id=pairing.user_id,
        device_name=pairing.device_name,
        token_hash=_hash_token(token),
        created_at=now,
        expires_at=now + DEVICE_TOKEN_TTL,
        last_used_at=None,
        revoked_at=None,
    )
    db.add(device)
    await db.commit()
    await store.reset_limit(f"device_claim_fail:{_client_ip(request)}")
    # The raw token is returned here and never again.
    return {
        "token": token,
        "device_id": device.id,
        "device_name": device.device_name,
        "expires_at": device.expires_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Paired devices (host)
# ---------------------------------------------------------------------------

def _device_row(device: PairedDevice) -> dict:
    return {
        "id": device.id,
        "device_name": device.device_name,
        "created_at": device.created_at.isoformat() if device.created_at else None,
        "expires_at": device.expires_at.isoformat() if device.expires_at else None,
        "last_used_at": device.last_used_at.isoformat() if device.last_used_at else None,
        "revoked": device.revoked_at is not None,
        "revoked_at": device.revoked_at.isoformat() if device.revoked_at else None,
    }


@router.get("/devices")
async def list_devices(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(
        select(PairedDevice)
        .where(PairedDevice.user_id == user.id)
        .order_by(PairedDevice.created_at.desc())
    )
    return {"devices": [_device_row(d) for d in result.scalars().all()]}


@router.delete("/devices/{device_id}")
async def revoke_device(device_id: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    device = await db.get(PairedDevice, device_id)
    if device is None or device.user_id != user.id:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.revoked_at is None:
        device.revoked_at = datetime.now(UTC)
        await db.commit()
    # The token stops working immediately: get_current_user rejects revoked rows.
    return {"ok": True, "device_id": device.id, "revoked": True}


@router.post("/devices/revoke-all")
async def revoke_all_devices(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(
        select(PairedDevice).where(
            PairedDevice.user_id == user.id, PairedDevice.revoked_at.is_(None)
        )
    )
    devices = result.scalars().all()
    now = datetime.now(UTC)
    for device in devices:
        device.revoked_at = now
    await db.commit()
    return {"ok": True, "revoked": len(devices)}


# ---------------------------------------------------------------------------
# LAN info + certificate (host)
# ---------------------------------------------------------------------------

@router.get("/devices/lan")
async def lan_info(request: Request, user=Depends(get_current_user)):
    host_header = (request.headers.get("host") or "").split(":")[0].lower()
    return {
        "ips": lan_ipv4_addresses(),
        "port": request.url.port or 8001,
        "loaded_via_loopback": host_header in ("localhost", "127.0.0.1", "::1", ""),
        "host_header": host_header,
    }


@router.get("/devices/cert")
async def get_cert(user=Depends(get_current_user)):
    return cert_info()


@router.post("/devices/cert/regenerate")
async def regenerate_cert(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    try:
        info = generate_cert()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    # A new certificate invalidates every pairing: a phone that pinned the
    # old fingerprint must not silently trust the new one.
    result = await db.execute(
        select(PairedDevice).where(
            PairedDevice.user_id == user.id, PairedDevice.revoked_at.is_(None)
        )
    )
    devices = result.scalars().all()
    now = datetime.now(UTC)
    for device in devices:
        device.revoked_at = now
    await db.commit()
    # Expire pending pairings in memory AND in the DB. The in-memory
    # count and the DB count must not double-count the same pairing
    # (a live pairing exists in both): DB rows whose pairing_id was
    # already expired in memory are updated but not counted again, so a
    # later restart cannot resurrect them as pending.
    live_ids = {
        pid for pid, p in PAIRINGS.items()
        if p.user_id == user.id and p.status in ("pending", "approved")
    }
    pairings_expired = expire_all_pairings()
    result = await db.execute(
        select(PendingPairing).where(
            PendingPairing.user_id == user.id,
            PendingPairing.status.in_(["pending", "approved"]),
        )
    )
    for row in result.scalars().all():
        row.status = "expired"
        if row.pairing_id not in live_ids:
            pairings_expired += 1
    await db.commit()
    return {
        **info,
        "devices_revoked": len(devices),
        "pairings_expired": pairings_expired,
        "warning": (
            "Regenerating the certificate invalidated all pairings: "
            f"{len(devices)} device(s) revoked and {pairings_expired} pending pairing(s) expired. "
            "Every device must pair again, and the server must be restarted with "
            "--ssl-certfile/--ssl-keyfile to serve the new certificate."
        ),
    }
