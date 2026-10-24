"""Phase 2 remainder tests: URL ingestion SSRF guard + endpoint,
memory export, and bulk forget guards.

The ingest endpoint's HTTP fetch is mocked (no real network in tests);
the SSRF guard itself is tested directly, including DNS-resolution
mocking for names that resolve to private addresses.
"""
from __future__ import annotations

import os
import socket
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from unittest.mock import AsyncMock, MagicMock, patch

from backend.ingest_url import IngestUrlError, html_to_text, slug_from_url, validate_url


def test_validate_url_rejects_schemes_and_credentials():
    for bad in ("ftp://example.com/x", "example.com/x", "", "http://user:pass@example.com/"):
        with pytest.raises(IngestUrlError):
            validate_url(bad)


def test_validate_url_rejects_literal_private_ips():
    for bad in ("http://127.0.0.1/admin", "http://10.0.0.5/", "http://192.168.1.1/",
                "http://169.254.169.254/latest/meta-data/", "http://[::1]/"):
        with pytest.raises(IngestUrlError):
            validate_url(bad)


def test_validate_url_rejects_private_dns_resolution():
    fake_infos = [(socket.AF_INET, None, None, None, ("10.1.2.3", 0))]
    with patch("backend.ingest_url.socket.getaddrinfo", return_value=fake_infos):
        with pytest.raises(IngestUrlError):
            validate_url("https://innocent.example.com/page")


def test_validate_url_accepts_public_dns_resolution():
    fake_infos = [(socket.AF_INET, None, None, None, ("93.184.216.34", 0))]
    with patch("backend.ingest_url.socket.getaddrinfo", return_value=fake_infos):
        assert validate_url("https://example.com/page") == "example.com"


def test_html_to_text_strips_script_and_tags():
    out = html_to_text("<html><head><style>.x{color:red}</style><script>alert(1)</script></head>"
                       "<body><h1>Hello &amp; welcome</h1><p>Some text.</p></body></html>")
    assert out == "Hello & welcome Some text."
    assert "alert" not in out and "color" not in out


def test_slug_from_url():
    assert slug_from_url("https://example.com/docs/guide") == "example.com-docs-guide.txt"
    assert slug_from_url("https://example.com/") == "example.com.txt"


def _api_client(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/phase2r.db")
    reset_engine_for_testing()
    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth(client):
    creds = {"username": "phase2r_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def test_ingest_url_endpoint_rejects_private_without_fetching(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    r = client.post("/api/knowledge/ingest-url", json={"url": "http://127.0.0.1/secret"}, headers=h)
    assert r.status_code == 422, r.text


def test_ingest_url_endpoint_mocked_fetch_and_stored(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_resp.content = b"<html><body><h1>Test Page</h1><p>Photosynthesis sunlight.</p></body></html>"
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_resp
    with patch("httpx.AsyncClient", return_value=mock_client), \
         patch("backend.ingest_url.socket.getaddrinfo",
               return_value=[(2, None, None, None, ("93.184.216.34", 0))]):
        r = client.post("/api/knowledge/ingest-url",
                        json={"url": "https://example.com/test-page"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filename"] == "example.com-test-page.txt"
    assert body["chunks_indexed"] >= 1
    assert "Photosynthesis" in body["preview"]
    # The ingested document is now retrievable through the hybrid endpoint.
    r = client.get("/api/knowledge/retrieve", params={"q": "photosynthesis"}, headers=h)
    assert r.status_code == 200, r.text
    assert any(res["citation"]["filename"] == "example.com-test-page.txt"
               for res in r.json()["results"])


def test_memory_export_and_bulk_forget(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    # Seed: 2 semantic, 1 episodic. Memory service uses Chroma (real, temp
    # path via TEST_MODE? — it uses its own persistent dir; to keep this
    # test hermetic, mock the memory service functions instead.)
    from backend.memory import models as _mm  # noqa: F401
    from datetime import datetime, timezone

    def _rec(id_, kind, content):
        rec = MagicMock()
        rec.id = id_
        rec.content = content
        rec.kind = MagicMock()
        rec.kind.value = kind
        rec.importance = 0.9
        rec.room = "default"
        rec.drawer = "general"
        rec.chat_id = ""
        rec.access_count = 0
        rec.created_at = datetime.now(timezone.utc)
        return rec

    seeded = [_rec("m1", "semantic", "alpha one"),
              _rec("m2", "semantic", "alpha two"),
              _rec("m3", "episodic", "beta three")]
    deleted: list[str] = []

    async def _list(kind=None, limit=50):
        return [r for r in seeded if kind is None or r.kind.value == kind.value]

    async def _delete(mid):
        deleted.append(mid)
        return True

    with patch("backend.api_routes.memory_routes.list_memories", side_effect=_list), \
         patch("backend.api_routes.memory_routes.delete_memory", side_effect=_delete):
        r = client.get("/api/memory/export", headers=h)
        assert r.status_code == 200, r.text
        assert len(r.json()) == 3
        assert "attachment" in r.headers.get("content-disposition", "")
        # Guard 1: no confirm -> 422, nothing deleted.
        r = client.post("/api/memory/forget", json={"kind": "semantic"}, headers=h)
        assert r.status_code == 422 and deleted == []
        # Guard 2: no filter -> 422 even with confirm.
        r = client.post("/api/memory/forget", json={"confirm": True}, headers=h)
        assert r.status_code == 422 and deleted == []
        # Real forget: only semantic deleted.
        r = client.post("/api/memory/forget", json={"kind": "semantic", "confirm": True}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["deleted"] == 2 and sorted(deleted) == ["m1", "m2"]
