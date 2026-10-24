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
