"""Phase 5 tests: OAuth connector framework, signed workflow webhooks,
versioned API alias, SDK/CLI, and backup/restore.

Connector token exchange is mocked (no real provider); the CLI/SDK
HTTP layer is mocked at urllib; backup/restore run on real temp files.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import zipfile
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from unittest.mock import AsyncMock, MagicMock, patch

from backend.connectors import ConnectorDefinition, make_state, register_connector, verify_state


def test_connector_state_roundtrip_and_tamper():
    state = make_state("github", "user-1")
    assert verify_state(state) == ("github", "user-1")
    assert verify_state(state) is None  # single-use
    assert verify_state("bogus.state") is None
    state2 = make_state("github", "user-1")
    tampered = state2[:-2] + "00"
    assert verify_state(tampered) is None


def _api_client(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/phase5.db")
    reset_engine_for_testing()
    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth(client):
    creds = {"username": "phase5_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def test_connectors_api_and_oauth_callback_mocked(tmp_path, monkeypatch):
    # Token storage encrypts with MASTER_KEY; set it for this test
    # (it is unset when this file runs alone).
    from cryptography.fernet import Fernet

    from backend.config import settings as _settings
    from backend.security import _get_fernet

    monkeypatch.setattr(_settings, "MASTER_KEY", Fernet.generate_key().decode())
    _get_fernet.cache_clear()
    monkeypatch.setenv("OAUTH_TESTPROV_CLIENT_ID", "cid")
    monkeypatch.setenv("OAUTH_TESTPROV_CLIENT_SECRET", "csecret")
    register_connector(ConnectorDefinition(
        name="testprov", label="Test Provider",
        authorize_url="https://provider.example/authorize",
        token_url="https://provider.example/token",
        scopes=["read"], client_id_env="OAUTH_TESTPROV_CLIENT_ID",
        client_secret_env="OAUTH_TESTPROV_CLIENT_SECRET",
    ))
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)

    r = client.get("/api/connectors", headers=h)
    assert r.status_code == 200, r.text
    prov = next(c for c in r.json()["connectors"] if c["name"] == "testprov")
    assert prov["configured"] is True and prov["connected"] is False

    r = client.get("/api/connectors/testprov/authorize", headers=h)
    assert r.status_code == 200, r.text
    state = r.json()["state"]
    assert "provider.example/authorize" in r.json()["authorize_url"]

    # Wrong state rejected before any exchange.
    assert client.get("/api/connectors/testprov/callback",
                      params={"code": "x", "state": "bad.state"}).status_code == 403

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "tok123", "refresh_token": "ref456", "expires_in": 3600}
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post.return_value = mock_resp
    with patch("httpx.AsyncClient", return_value=mock_client):
        r = client.get("/api/connectors/testprov/callback", params={"code": "abc", "state": state})
    assert r.status_code == 200, r.text
    assert r.json()["connected"] is True
    r = client.get("/api/connectors", headers=h)
    prov = next(c for c in r.json()["connectors"] if c["name"] == "testprov")
    assert prov["connected"] is True
    r = client.delete("/api/connectors/testprov", headers=h)
    assert r.status_code == 200
    assert client.get("/api/connectors/testprov/authorize", headers=h).status_code == 200  # still configured


def test_signed_workflow_webhook(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    wf = client.post("/api/workflows", json={
        "name": "Sig test",
        "definition": {"nodes": [{"id": "a", "type": "text", "config": {"template": "hi {{input.name}}"}}], "edges": []},
        "trigger": "manual",
    }, headers=h).json()
    wid, secret = wf["id"], wf["webhook_secret"]
    assert secret
    body = json.dumps({"name": "Ada"}).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    from fastapi.testclient import TestClient as _TC
    from backend.main import create_app

    wc = _TC(create_app())
    # Signed, no token: works.
    r = wc.post(f"/api/workflows/{wid}/webhook", content=body,
                headers={"Content-Type": "application/json", "X-Sangam-Signature": sig})
    assert r.status_code == 201, r.text
    assert r.json()["output"]["a"] == "hi Ada"
    # Wrong signature: 404.
    r = wc.post(f"/api/workflows/{wid}/webhook", content=body,
                headers={"Content-Type": "application/json", "X-Sangam-Signature": "sha256=00"})
    assert r.status_code == 404


def test_versioned_api_alias_and_backup(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    # /api/v1 mirrors /api for the same authenticated caller.
    assert client.get("/api/v1/workflows", headers=h).status_code == 200
    r = client.get("/api/system/backup", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(__import__("io").BytesIO(r.content)) as zf:
        assert "sangam.db" in zf.namelist()


def test_sdk_and_cli_backup_restore(tmp_path, monkeypatch):
    # SDK: mocked urllib transport.
    import sangam_client as sc

    class FakeResp:
        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return json.dumps(self.payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.header_items())
        return FakeResp({"workflows": [{"id": "wf-1"}]})

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client = sc.SangamClient(base_url="http://x:8001", token="tok")
        assert client.list_workflows() == [{"id": "wf-1"}]
        assert seen["url"] == "http://x:8001/api/v1/workflows"
        assert seen["headers"]["Authorization"] == "Bearer tok"

    # CLI backup/restore on real temp files.
    import cli

    db = tmp_path / "src.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.execute("INSERT INTO t VALUES ('hello')")
    conn.commit()
    conn.close()
    uploads = tmp_path / "uploads"
    (uploads / "sub").mkdir(parents=True)
    (uploads / "sub" / "a.txt").write_text("data")
    out = tmp_path / "bk.zip"
    cli.backup_zip(db, uploads, out)
    with zipfile.ZipFile(out) as zf:
        assert "sangam.db" in zf.namelist() and "uploads/sub/a.txt" in zf.namelist()
    data_dir = tmp_path / "restored"
    cli.restore_zip(out, data_dir)
    conn = sqlite3.connect(str(data_dir / "sangam.db"))
    assert conn.execute("SELECT v FROM t").fetchone()[0] == "hello"
    assert (data_dir / "uploads" / "sub" / "a.txt").read_text() == "data"
