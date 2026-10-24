"""Batch 6 (LAN Pairing) tests.

Covers: LAN_ENABLED defaults off + start gating, pairing lifecycle
(start -> claim-before-approval waits -> approve -> claim once, second
claim fails, denied/expired codes fail generically), claim lockout
(5 wrong codes -> 429, correct claim during lockout refused, reset then
success), device-token auth on a protected route, raw token never stored
(only its SHA-256 hash), revoked/expired tokens -> 401 with
machine-readable details, host session still valid after pairing and
after device-token use (the _create_session regression), cert
regeneration revoking all devices + expiring pending pairings,
pairing-start rate limiting, and LAN info.

Live TestClient flow (register -> Bearer), fresh SQLite DB per test,
following the Batch 2/4/5 precedent. Claim calls use a fresh TestClient
with no cookies, as a phone would. No real certificate is required for
the unit tests except the cert test, which redirects the cert dir to
tmp and uses the real cryptography path (present in the venv).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import backend.api_routes.devices_routes  # noqa: E402,F401 — registers routes + tables
import backend.lan_pairing as lan_pairing  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.database import AsyncSessionLocal, Base, get_engine, reset_engine_for_testing  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.ratelimit_redis import reset_rate_limit_store_for_testing  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _api_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/b6.db")
    reset_engine_for_testing()
    reset_rate_limit_store_for_testing()
    lan_pairing.PAIRINGS.clear()

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


@pytest.fixture
def client(tmp_path, monkeypatch):
    return _api_client(tmp_path, monkeypatch)


@pytest.fixture
def fresh_client():
    # A second client with no cookies: the phone. Shares module-level
    # state (pairings, rate-limit store) and the test DB with `client`.
    return TestClient(create_app())


def _auth_headers(client):
    creds = {"username": "b6_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    # The register/login response also sets the sangam_csrf cookie on this
    # client; state-changing POSTs must echo it back (Batch 3 precedent).
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


def _enable_lan(client, headers):
    cur = client.get("/api/user/settings", headers=headers).json().get("settings", {})
    r = client.put("/api/user/settings", json={"settings": {**cur, "LAN_ENABLED": True}}, headers=headers)
    assert r.status_code == 200, r.text
    return r


def _start(client, headers, name="Phone"):
    r = client.post("/api/devices/pairing/start", json={"device_name": name}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _claim(phone, code):
    return phone.post("/api/devices/pairing/claim", json={"code": code})


def _pair_device(client, headers, phone, name="Phone"):
    """start -> approve -> claim; returns (pairing, claim_body)."""
    pairing = _start(client, headers, name)
    r = client.post(f"/api/devices/pairing/{pairing['pairing_id']}/approve", json={}, headers=headers)
    assert r.status_code == 200, r.text
    claim = _claim(phone, pairing["code"])
    assert claim.status_code == 200, claim.text
    return pairing, claim.json()


def _db_device(device_id):
    async def _get():
        from sqlalchemy import select

        from backend.lan_pairing import PairedDevice

        async with AsyncSessionLocal() as session:
            return await session.scalar(select(PairedDevice).where(PairedDevice.id == device_id))

    return asyncio.run(_get())


def _expire_db_device(device_id):
    async def _run():
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import select

        from backend.lan_pairing import PairedDevice

        async with AsyncSessionLocal() as session:
            device = await session.scalar(select(PairedDevice).where(PairedDevice.id == device_id))
            device.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(_run())


# ---------------------------------------------------------------- LAN default
def test_lan_defaults_off(client):
    headers = _auth_headers(client)
    settings_blob = client.get("/api/user/settings", headers=headers).json().get("settings", {})
    assert not settings_blob.get("LAN_ENABLED")


def test_pairing_start_requires_lan_on(client):
    headers = _auth_headers(client)
    r = client.post("/api/devices/pairing/start", json={"device_name": "Phone"}, headers=headers)
    assert r.status_code == 403
    assert "LAN mode is off" in r.json()["detail"]


# ---------------------------------------------------------------- lifecycle
def test_pairing_lifecycle(client, fresh_client):
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    pairing = _start(client, headers)
    assert re.fullmatch(r"\d{6}", pairing["code"])
    assert pairing["status"] == "pending"
    payload = json.loads(pairing["payload"])
    assert payload["code"] == pairing["code"]
    assert payload["url"].startswith("http://")
    assert "fingerprint" in payload

    # Claim before approval: waits, does not grant.
    r = _claim(fresh_client, pairing["code"])
    assert r.status_code == 403
    assert r.json()["detail"] == "waiting for host approval"

    # Approve -> claim succeeds exactly once, returning the raw token.
    r = client.post(f"/api/devices/pairing/{pairing['pairing_id']}/approve", json={}, headers=headers)
    assert r.status_code == 200
    claim = _claim(fresh_client, pairing["code"])
    assert claim.status_code == 200
    body = claim.json()
    assert body["token"] and body["device_id"] and body["expires_at"]

    # Second claim with the same code fails (single-use).
    again = _claim(fresh_client, pairing["code"])
    assert again.status_code == 404
    assert again.json()["detail"] == "invalid or expired code"

    # Device token authenticates a protected route.
    token_headers = {"Authorization": f"Bearer {body['token']}"}
    r = fresh_client.get("/api/devices", headers=token_headers)
    assert r.status_code == 200

    # The raw token is NOT in the DB row — only its SHA-256 hash.
    row = _db_device(body["device_id"])
    assert row is not None
    assert row.token_hash == hashlib.sha256(body["token"].encode()).hexdigest()
    assert row.token_hash != body["token"]

    # The device list never exposes hashes or raw tokens.
    listed = fresh_client.get("/api/devices", headers=token_headers).json()["devices"]
    assert any(d["id"] == body["device_id"] for d in listed)
    assert "token_hash" not in json.dumps(listed)
    assert body["token"] not in json.dumps(listed)


def test_denied_code_claim_fails(client, fresh_client):
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    pairing = _start(client, headers)
    r = client.post(f"/api/devices/pairing/{pairing['pairing_id']}/deny", json={}, headers=headers)
    assert r.status_code == 200
    claim = _claim(fresh_client, pairing["code"])
    assert claim.status_code == 404
    assert claim.json()["detail"] == "invalid or expired code"


def test_expired_pairing_claim_fails(client, fresh_client):
    from datetime import UTC, datetime, timedelta

    headers = _auth_headers(client)
    _enable_lan(client, headers)
    pairing = _start(client, headers)
    client.post(f"/api/devices/pairing/{pairing['pairing_id']}/approve", json={}, headers=headers)
    lan_pairing.PAIRINGS[pairing["pairing_id"]].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    claim = _claim(fresh_client, pairing["code"])
    assert claim.status_code == 404
    assert claim.json()["detail"] == "invalid or expired code"


def test_wrong_code_is_generic(client, fresh_client):
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    claim = _claim(fresh_client, "000000")
    assert claim.status_code == 404
    assert claim.json()["detail"] == "invalid or expired code"


def test_claim_lockout(client, fresh_client):
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    pairing = _start(client, headers)
    client.post(f"/api/devices/pairing/{pairing['pairing_id']}/approve", json={}, headers=headers)
    # 5 wrong codes -> each a generic 404 ...
    for i in range(5):
        r = _claim(fresh_client, f"11111{i}")
        assert r.status_code == 404, r.text
    # ... then even the CORRECT code is refused during lockout.
    r = _claim(fresh_client, pairing["code"])
    assert r.status_code == 429
    # After the lockout is cleared, the correct claim succeeds.
    reset_rate_limit_store_for_testing()
    r = _claim(fresh_client, pairing["code"])
    assert r.status_code == 200, r.text


def test_pairing_status_host(client):
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    pairing = _start(client, headers)
    r = client.get(f"/api/devices/pairing/{pairing['pairing_id']}", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    client.post(f"/api/devices/pairing/{pairing['pairing_id']}/approve", json={}, headers=headers)
    r = client.get(f"/api/devices/pairing/{pairing['pairing_id']}", headers=headers)
    assert r.json()["status"] == "approved"


# ---------------------------------------------------------------- tokens
def test_revoked_token_401(client, fresh_client):
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    _, body = _pair_device(client, headers, fresh_client)
    token_headers = {"Authorization": f"Bearer {body['token']}"}
    r = client.delete(f"/api/devices/{body['device_id']}", headers=headers)
    assert r.status_code == 200
    r = fresh_client.get("/api/devices", headers=token_headers)
    assert r.status_code == 401
    assert r.json()["detail"] == "device_revoked"


def test_expired_token_401(client, fresh_client):
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    _, body = _pair_device(client, headers, fresh_client)
    _expire_db_device(body["device_id"])
    r = fresh_client.get("/api/devices", headers={"Authorization": f"Bearer {body['token']}"})
    assert r.status_code == 401
    assert r.json()["detail"] == "device_expired"


def test_revoke_all(client, fresh_client):
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    _, body1 = _pair_device(client, headers, fresh_client, "Phone A")
    _, body2 = _pair_device(client, headers, fresh_client, "Phone B")
    r = client.post("/api/devices/revoke-all", json={}, headers=headers)
    assert r.status_code == 200
    assert r.json()["revoked"] == 2
    for token in (body1["token"], body2["token"]):
        r = fresh_client.get("/api/devices", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401


def test_host_session_survives_pairing(client, fresh_client):
    """Regression: pairing a phone must NOT log out the laptop.
    _create_session deletes all previous sessions; device tokens must
    never go through it."""
    # Cookie session: register on this client (cookies auto-stored).
    creds = {"username": "b6_cookie_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    assert r.status_code == 201, r.text
    csrf = client.cookies.get("sangam_csrf")
    cookie_headers = {"X-CSRF-Token": csrf} if csrf else {}
    # Cookie-only auth works before pairing.
    assert client.get("/api/devices").status_code == 200
    # Enable LAN + pair via the cookie session.
    cur = client.get("/api/user/settings").json().get("settings", {})
    r = client.put("/api/user/settings", json={"settings": {**cur, "LAN_ENABLED": True}}, headers=cookie_headers)
    assert r.status_code == 200, r.text
    pairing = client.post("/api/devices/pairing/start", json={"device_name": "Phone"}, headers=cookie_headers).json()
    r = client.post(f"/api/devices/pairing/{pairing['pairing_id']}/approve", json={}, headers=cookie_headers)
    assert r.status_code == 200, r.text
    claim = _claim(fresh_client, pairing["code"])
    assert claim.status_code == 200
    token = claim.json()["token"]
    # The device token works...
    assert fresh_client.get("/api/devices", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    # ...and the laptop's cookie session STILL works afterwards.
    assert client.get("/api/devices").status_code == 200


# ---------------------------------------------------------------- cert + misc
def test_cert_regenerate_revokes_all(client, fresh_client, tmp_path, monkeypatch):
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    # Redirect the cert dir to tmp so tests never touch the repo tree.
    cert_dir = tmp_path / "lan-cert"
    monkeypatch.setattr(lan_pairing, "CERT_DIR", cert_dir)
    monkeypatch.setattr(lan_pairing, "CERT_FILE", cert_dir / "cert.pem")
    monkeypatch.setattr(lan_pairing, "KEY_FILE", cert_dir / "key.pem")

    info = client.get("/api/devices/cert", headers=headers).json()
    assert info["exists"] is False

    _, body = _pair_device(client, headers, fresh_client)
    pending = _start(client, headers, "Tablet")
    r = client.post("/api/devices/cert/regenerate", json={}, headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert re.fullmatch(r"[0-9a-f]{64}", data["fingerprint_sha256"])
    assert data["devices_revoked"] == 1
    assert data["pairings_expired"] == 1
    assert "invalidated" in data["warning"]
    # The paired device token is dead; the pending pairing is expired.
    r = fresh_client.get("/api/devices", headers={"Authorization": f"Bearer {body['token']}"})
    assert r.status_code == 401
    r = client.get(f"/api/devices/pairing/{pending['pairing_id']}", headers=headers)
    assert r.json()["status"] == "expired"


def test_pairing_start_rate_limit(client):
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    for _ in range(10):
        r = client.post("/api/devices/pairing/start", json={"device_name": "Phone"}, headers=headers)
        assert r.status_code == 200, r.text
    r = client.post("/api/devices/pairing/start", json={"device_name": "Phone"}, headers=headers)
    assert r.status_code == 429


def test_lan_info(client):
    headers = _auth_headers(client)
    r = client.get("/api/devices/lan", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["ips"], list)
    assert isinstance(data["port"], int)
    assert "loaded_via_loopback" in data


def _set_lan(client, headers, value):
    cur = client.get("/api/user/settings", headers=headers).json().get("settings", {})
    r = client.put("/api/user/settings", json={"settings": {**cur, "LAN_ENABLED": value}}, headers=headers)
    assert r.status_code == 200, r.text
    return r


def _restarted_client():
    """Simulate a server restart: drop all in-memory pairing state and
    build a fresh app against the SAME database (same tmp DB file, same
    engine — the fresh_client pattern, plus a cleared PAIRINGS cache)."""
    lan_pairing.PAIRINGS.clear()
    return TestClient(create_app())


def _expire_db_pairing(pairing_id):
    async def _run():
        from datetime import UTC, datetime, timedelta

        from backend.lan_pairing import PendingPairing

        async with AsyncSessionLocal() as session:
            row = await session.get(PendingPairing, pairing_id)
            assert row is not None
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(_run())


# ------------------------------------------------------- restart persistence
def test_pending_pairing_survives_restart(client, fresh_client):
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    pairing = _start(client, headers, "Phone")
    # Restart: in-memory state is gone, the DB row remains.
    restarted = _restarted_client()
    assert pairing["pairing_id"] not in lan_pairing.PAIRINGS
    # The host still sees the pending pairing on the restarted app and
    # can approve it by device name...
    listed = restarted.get("/api/devices/pairing", headers=headers).json()["pairings"]
    match = [p for p in listed if p["pairing_id"] == pairing["pairing_id"]]
    assert len(match) == 1 and match[0]["status"] == "pending"
    # ...but the code digits are NOT recoverable from the DB: only its
    # SHA-256 hash is stored (same pattern as device token hashes).
    assert match[0]["code"] is None
    r = restarted.post(f"/api/devices/pairing/{pairing['pairing_id']}/approve", json={}, headers=headers)
    assert r.status_code == 200, r.text
    # ...and the phone, which still holds the code from the QR, claims.
    claim = _claim(fresh_client, pairing["code"])
    assert claim.status_code == 200, claim.text
    body = claim.json()
    token_headers = {"Authorization": f"Bearer {body['token']}"}
    assert fresh_client.get("/api/devices", headers=token_headers).status_code == 200


def test_claim_before_approval_still_waits_after_restart(client, fresh_client):
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    pairing = _start(client, headers, "Phone")
    _restarted_client()
    # Correct code, host has not approved yet — even after a restart
    # the phone must wait, not be granted and not be told the code is bad.
    r = _claim(fresh_client, pairing["code"])
    assert r.status_code == 403
    assert r.json()["detail"] == "waiting for host approval"


def test_expired_pending_pairing_still_fails_after_restart(client, fresh_client):
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    pairing = _start(client, headers, "Phone")
    _expire_db_pairing(pairing["pairing_id"])
    _restarted_client()
    claim = _claim(fresh_client, pairing["code"])
    assert claim.status_code == 404
    assert claim.json()["detail"] == "invalid or expired code"


def test_claim_single_use_survives_restart(client, fresh_client):
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    pairing = _start(client, headers, "Phone")
    client.post(f"/api/devices/pairing/{pairing['pairing_id']}/approve", json={}, headers=headers)
    _restarted_client()
    first = _claim(fresh_client, pairing["code"])
    assert first.status_code == 200, first.text
    # Consumed once: a second claim fails, even after another restart
    # (the claimed status was written back to the DB row).
    _restarted_client()
    again = _claim(fresh_client, pairing["code"])
    assert again.status_code == 404
    assert again.json()["detail"] == "invalid or expired code"


# ------------------------------------------------------- LAN-off enforcement
def test_device_token_rejected_when_lan_disabled(client, fresh_client):
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    _, body = _pair_device(client, headers, fresh_client)
    token_headers = {"Authorization": f"Bearer {body['token']}"}
    assert fresh_client.get("/api/devices", headers=token_headers).status_code == 200

    # Toggle LAN off: the previously valid device token now 401s with a
    # machine-readable detail the phone UI maps to plain language...
    _set_lan(client, headers, False)
    r = fresh_client.get("/api/devices", headers=token_headers)
    assert r.status_code == 401
    assert r.json()["detail"] == "lan_disabled"
    # ...while the host's own session auth is unaffected.
    assert client.get("/api/devices", headers=headers).status_code == 200

    # Toggle back on: the token works again — LAN-off suspends devices,
    # it does not revoke them, so no re-pairing is required.
    _enable_lan(client, headers)
    assert fresh_client.get("/api/devices", headers=token_headers).status_code == 200


def test_revoked_beats_lan_disabled_detail(client, fresh_client):
    """Precedence: a revoked token reports device_revoked even with LAN
    off, so revocation (the explicit kill switch) is never masked."""
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    _, body = _pair_device(client, headers, fresh_client)
    token_headers = {"Authorization": f"Bearer {body['token']}"}
    client.delete(f"/api/devices/{body['device_id']}", headers=headers)
    _set_lan(client, headers, False)
    r = fresh_client.get("/api/devices", headers=token_headers)
    assert r.status_code == 401
    assert r.json()["detail"] == "device_revoked"
    # Parent fix: a password reset must kill paired-device tokens too,
    # or a stolen phone token survives the credential it was paired under.
    headers = _auth_headers(client)
    _enable_lan(client, headers)
    _, claim = _pair_device(client, headers, fresh_client)
    token_headers = {"Authorization": f"Bearer {claim['token']}"}
    assert fresh_client.get("/api/devices", headers=token_headers).status_code == 200

    forgot = client.post("/api/auth/forgot-password", json={"username": "b6_user"})
    assert forgot.status_code == 200, forgot.text
    resp = client.post("/api/auth/reset-password", json={
        "reset_token": forgot.json()["reset_token"],
        "new_password": "NewStrongPass456!",
    })
    assert resp.status_code == 200, resp.text

    row = _db_device(claim["device_id"])
    assert row is not None and row.revoked_at is not None
    r = fresh_client.get("/api/devices", headers=token_headers)
    assert r.status_code == 401
    assert r.json()["detail"] == "device_revoked"
