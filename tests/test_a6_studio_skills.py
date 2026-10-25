"""A6 (Studio, Skills & Integrations) tests — spec/a6-studio-skills.

Covers, all via the live TestClient (register -> Bearer, fresh SQLite
DB per test, no ports, no network):
  * provider adapter contract: all six contract methods exist on
    BaseProvider; normalize_error maps 429 -> rate_limit (retryable)
    and 401 -> authentication_error; contract-check reports every
    registered provider.
  * capability registry: all 11 providers present (incl. OmniRoute);
    preflight warns "this model can't do X" for a model known to lack
    it (nim-llama-3-1-8b has no vision/reasoning) and reports unknown
    for an unregistered model instead of inventing support.
  * cost-ranked routing: known prices cheapest-first, unknown last
    with cost_known=False.
  * studio documents: docx/pptx/xlsx outputs PARSE BACK with the real
    libraries (python-docx / python-pptx / openpyxl); pdf starts %PDF.
  * diagrams: catalogue has exactly 44 unique types; node/edge export
    parses as XML (svg) and embeds the SVG (html); png is refused 422.
  * classroom: topic+source -> slides grounded in the source, quiz
    with a valid answer index, interactive HTML, PBL milestones; no
    MP4 is offered.
  * marketplace: registry source is labelled stub; pack dry-run writes
    nothing; pack install for the three approved packs (engineering,
    science-essentials, creative-design) verifies against the lockfile.
  * connectors: health/permissions for an unconfigured connector
    report configured/connected without ever returning a token value.
  * blind compare: outputs are labelled A/B only, and a vote reveals
    the real winner and records an Arena row (stream mocked, no model).
  * model fit advisor: hardware-aware fit_score still distinguishes
    fits / does-not-fit (extended, not rewritten).
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import patch

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from backend.config import settings  # noqa: E402
from backend.database import Base, get_engine, reset_engine_for_testing  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.model_fit import fit_score  # noqa: E402
from backend.providers.base import BaseProvider  # noqa: E402
from backend.providers.contract import (  # noqa: E402
    capability_registry,
    cost_ranked_route,
    preflight,
)
from backend.ratelimit_redis import reset_rate_limit_store_for_testing  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _api_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL",
                        "sqlite+aiosqlite:///" + str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    reset_engine_for_testing()
    reset_rate_limit_store_for_testing()

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


@pytest.fixture
def client(tmp_path, monkeypatch):
    return _api_client(tmp_path, monkeypatch)


def _auth_headers(client):
    creds = {"username": "a6_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


# ---------------------------------------------------------------- providers
def test_contract_methods_exist_on_base_provider():
    for method in ("capabilities", "stream", "tools", "reasoning",
                   "citations", "normalize_error", "stream_completion"):
        assert hasattr(BaseProvider, method), method


def test_normalize_error_maps_rate_limit_and_auth():
    from backend.providers.base import ProviderConfig

    class _P(BaseProvider):
        async def list_models(self, api_key=None):
            return []

        async def stream_completion(self, *a, **k):
            yield "x"

    cfg = ProviderConfig(provider_id="openai", label="OpenAI", local=False,
                         env_key_name="", api_base="https://x", model_endpoint="https://x")
    provider = _P.__new__(_P)
    provider.config = cfg

    class _Resp:
        status_code = 429

        def json(self):
            return {}

    import httpx

    req = httpx.Request("GET", "https://x")
    err = httpx.HTTPStatusError("rate limited", request=req, response=httpx.Response(429, request=req))
    norm = provider.normalize_error(err, model="gpt-4o")
    assert norm.category == "rate_limit" and norm.retryable is True
    assert norm.provider == "openai" and norm.model == "gpt-4o"
    err401 = httpx.HTTPStatusError("unauthorized", request=req, response=httpx.Response(401, request=req))
    assert provider.normalize_error(err401).category == "authentication_error"


def test_capability_registry_lists_all_eleven_providers(client):
    h = _auth_headers(client)
    r = client.get("/api/providers/capability-registry", headers=h)
    assert r.status_code == 200, r.text
    ids = {p["provider_id"] for p in r.json()["providers"]}
    for pid in ("anthropic", "openai", "nvidia", "together", "groq",
                "openrouter", "deepseek", "mistral", "gemini", "ollama", "omniroute"):
        assert pid in ids, pid


def test_preflight_warns_model_cant_do_vision_and_reasoning(client):
    h = _auth_headers(client)
    r = client.post("/api/providers/preflight", headers=h, json={
        "provider": "nvidia", "model": "nim-llama-3-1-8b",
        "wanted": ["vision", "reasoning", "tools"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["capabilities_known"] is True
    assert set(data["blocked"]) == {"vision", "reasoning"}
    assert any("can't do vision" in w for w in data["warnings"])
    assert any("can't do reasoning" in w for w in data["warnings"])


def test_preflight_unknown_model_reports_unknown_not_supported(client):
    h = _auth_headers(client)
    r = client.post("/api/providers/preflight", headers=h, json={
        "provider": "openai", "model": "definitely-not-a-model",
        "wanted": ["tools"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["capabilities_known"] is False
    assert data["capabilities"] is None
    assert data["blocked"] == []


def test_contract_check_reports_adapters(client):
    h = _auth_headers(client)
    r = client.get("/api/providers/contract-check", headers=h)
    assert r.status_code == 200, r.text
    rows = r.json()["adapters"]
    assert len(rows) == 11
    assert all(rw["contract_ok"] for rw in rows), rows
    assert all(set(rw["methods"]) >= {"capabilities", "stream", "tools",
                                      "reasoning", "citations", "normalize_error"}
               for rw in rows)


def test_cost_ranked_cheapest_first_unknown_last():
    ranked = cost_ranked_route([
        {"provider": "a", "model": "m1"},
        {"provider": "b", "model": "m2", "price_per_1k_usd": 0.9},
        {"provider": "c", "model": "m3", "price_per_1k_usd": 0.1},
    ])
    assert [r["model"] for r in ranked] == ["m3", "m2", "m1"]
    assert ranked[-1]["cost_known"] is False
    assert ranked[0]["cost_known"] is True


def test_cost_ranked_endpoint(client):
    h = _auth_headers(client)
    r = client.post("/api/providers/cost-ranked", headers=h, json={
        "candidates": [{"provider": "x", "model": "m", "price_per_1k_usd": 2.0},
                       {"provider": "y", "model": "n"}]})
    assert r.status_code == 200, r.text
    assert [c["model"] for c in r.json()["ranked"]] == ["m", "n"]


def test_fit_score_hardware_aware():
    fits = fit_score(3.0, "Q4_K", 32, 2048, 8192, budget_gb=16.0)
    assert fits["fits"] is True and fits["bottleneck"] == "none"
    too_big = fit_score(70.0, "Q4_K", 80, 8192, 8192, budget_gb=8.0)
    assert too_big["fits"] is False and too_big["bottleneck"] in ("weights", "kv-cache")


# ------------------------------------------------------------------- studio
def test_document_proof_parses_back_all_formats(client):
    h = _auth_headers(client)
    sections = [{"heading": "Intro", "body": "Hello world"}]
    rows = [["a", "b"], [1, 2]]
    for fmt in ("docx", "pptx", "xlsx", "pdf"):
        r = client.post("/api/studio/documents/proof", headers=h, json={
            "format": fmt, "title": "Proof doc", "sections": sections, "rows": rows})
        assert r.status_code == 200, (fmt, r.text)
        data = r.json()
        assert len(data["sha256"]) == 64
        parsed = data["parsed"]
        if fmt == "docx":
            import docx

            assert "Proof doc" in parsed["paragraphs"]
            assert "Hello world" in parsed["paragraphs"]
        elif fmt == "pptx":
            assert parsed["slides"] >= 1
        elif fmt == "xlsx":
            assert "Sheet1" in parsed["sheets"]
        else:
            assert parsed["starts_with_pdf"] is True


def test_document_proof_rejects_unknown_format(client):
    h = _auth_headers(client)
    r = client.post("/api/studio/documents/proof", headers=h,
                    json={"format": "odt", "title": "x"})
    assert r.status_code == 422


def test_diagram_catalogue_has_44_unique_types(client):
    h = _auth_headers(client)
    r = client.get("/api/diagrams/catalogue", headers=h)
    assert r.status_code == 200, r.text
    ids = [d["id"] for d in r.json()["diagrams"]]
    assert len(ids) == 44 and len(set(ids)) == 44


def test_diagram_export_svg_parses_as_xml_and_html_embeds_it(client):
    h = _auth_headers(client)
    payload = {"title": "Flow", "accent": "#123456",
               "nodes": [{"id": "a", "label": "Start", "shape": "rect"},
                         {"id": "b", "label": "End", "shape": "ellipse"}],
               "edges": [{"from": "a", "to": "b", "label": "go"},
                         {"from": "a", "to": "ghost"}]}
    r = client.post("/api/diagrams/export", headers=h,
                    json={**payload, "format": "svg"})
    assert r.status_code == 200, r.text
    root = ET.fromstring(r.json()["content"])
    assert root.tag.endswith("svg")
    assert r.json()["report"] == {"nodes": 2, "edges": 2,
                                  "rendered_edges": 1, "dropped_edges": 1}
    r = client.post("/api/diagrams/export", headers=h,
                    json={**payload, "format": "html"})
    assert r.status_code == 200, r.text
    assert "<svg" in r.json()["content"] and "<!doctype html>" in r.json()["content"].lower()


def test_diagram_export_png_refused_not_faked(client):
    h = _auth_headers(client)
    r = client.post("/api/diagrams/export", headers=h,
                    json={"format": "png", "nodes": [], "edges": []})
    assert r.status_code == 422


def test_classroom_generate_grounded_and_honest(client):
    h = _auth_headers(client)
    r = client.post("/api/studio/classroom/generate", headers=h, json={
        "topic": "Photosynthesis",
        "source_text": "Plants capture sunlight in leaves. Chlorophyll drives the reaction."})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["source_based"] is True
    assert any("sunlight" in b for s in data["slides"] for b in s["bullets"])
    assert all(0 <= q["answer_index"] < len(q["options"]) for q in data["quiz"])
    assert "Photosynthesis" in data["interactive_html"]
    assert len(data["pbl"]["milestones"]) == 4
    assert "mp4" in data["not_offered"]
    # Skeleton path labels itself instead of inventing content.
    r = client.post("/api/studio/classroom/generate", headers=h,
                    json={"topic": "Mystery topic"})
    assert r.json()["source_based"] is False
    assert r.json()["slides"][0]["skeleton"] is True


def test_studio_catalog_lists_families_and_skips(client):
    h = _auth_headers(client)
    r = client.get("/api/studio/catalog", headers=h)
    assert r.status_code == 200, r.text
    fams = {f["id"]: f for f in r.json()["families"]}
    for fid in ("documents", "design", "diagrams", "image", "voice", "classroom"):
        assert fid in fams
    assert fams["diagrams"]["types"] == 44
    assert "voice cloning" in str(fams["voice"].get("not_offered"))
    assert fams["video"]["available"] is False


# -------------------------------------------------------------- marketplace
def test_marketplace_registry_source_labelled_stub(client):
    h = _auth_headers(client)
    r = client.get("/api/marketplace/sources", headers=h)
    assert r.status_code == 200, r.text
    sources = {s["id"]: s for s in r.json()["sources"]}
    assert sources["registry"]["status"] == "stub"
    assert "STUB" in sources["registry"]["note"]


def _redirect_skill_roots(tmp_path, monkeypatch):
    """Point skill installs/locks at a tmp root (Batch 5 precedent)."""
    import backend.skills.packs as packs_mod
    import backend.skills.verify as verify_mod

    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setattr(verify_mod, "USER_SKILLS_ROOT", root)
    monkeypatch.setattr(verify_mod, "LOCK_FILE", root / "skills-lock.json")
    monkeypatch.setattr(packs_mod, "SKILLS_CONFIG_ROOT", root)
    monkeypatch.setattr(packs_mod, "PACKS_LOCK_FILE", root / "packs-lock.json")
    monkeypatch.setattr(packs_mod, "PACK_STATE_FILE", root / ".pack_state.json")
    return root


def test_pack_dry_run_writes_nothing(client, tmp_path, monkeypatch):
    _redirect_skill_roots(tmp_path, monkeypatch)
    h = _auth_headers(client)
    for pack in ("engineering", "science-essentials", "creative-design"):
        r = client.post(f"/api/marketplace/packs/{pack}/dry-run", headers=h)
        assert r.status_code == 200, (pack, r.text)
        data = r.json()
        assert data["writes_nothing"] is True
        assert data["skills"], pack
        for skill in data["skills"]:
            assert skill["files"], skill
            assert all(len(f["sha256"]) == 64 for f in skill["files"])
    assert not list((tmp_path / "skills").glob("*/SKILL.md"))


def test_pack_install_hash_verified_for_three_approved_packs(client, tmp_path, monkeypatch):
    root = _redirect_skill_roots(tmp_path, monkeypatch)
    h = _auth_headers(client)
    from backend.skills.verify import verify_lock

    for pack in ("engineering", "science-essentials", "creative-design"):
        r = client.post(f"/api/marketplace/packs/{pack}/install", headers=h)
        assert r.status_code == 200, (pack, r.text)
        data = r.json()
        assert data["lock_verified"], pack
        assert not any(i["blocked_by_scan"] for i in data["installed"])
    rows = {row["name"]: row["status"] for row in verify_lock()}
    assert rows and all(status == "ok" for status in rows.values())


def test_pack_dry_run_unknown_pack_404(client):
    h = _auth_headers(client)
    r = client.post("/api/marketplace/packs/no-such-pack/dry-run", headers=h)
    assert r.status_code == 404


# --------------------------------------------------------------- connectors
def test_connector_health_and_permissions_no_token_leak(client):
    h = _auth_headers(client)
    r = client.get("/api/connectors/github/health", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["connected"] is False
    assert data["token"] is None
    r = client.get("/api/connectors/github/permissions", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["requested_scopes"] and data["granted_scopes"] == []
    assert data["token_value"] is None
    assert "encrypted_at_rest" in data["credential_storage"]
    r = client.get("/api/connectors/no-such/health", headers=h)
    assert r.status_code == 404


# ----------------------------------------------------------- blind compare
def test_blind_compare_labels_only_and_vote_reveals(client, tmp_path, monkeypatch):
    h = _auth_headers(client)

    async def _fake_stream(model_id, messages, db, max_tokens=None):
        yield "neutral answer"

    with patch("backend.llm.stream_completion", side_effect=_fake_stream):
        r = client.post("/api/compare/blind", headers=h, json={
            "prompt": "Say hi", "models": ["model-one", "model-two"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert [res["label"] for res in data["results"]] == ["A", "B"]
    assert "model-one" not in str(data["results"])
    assert "model-two" not in str(data["results"])
    r = client.post("/api/compare/blind/vote", headers=h, json={
        "blind_id": data["blind_id"], "winner_label": "B"})
    assert r.status_code == 201, r.text
    assert r.json()["winner_model"] == "model-two"
    r = client.get("/api/arena/leaderboard", headers=h)
    assert r.status_code == 200, r.text
    assert any(row.get("model") == "model-two"
               for row in r.json()["leaderboard"])


def test_blind_vote_unknown_id_404(client):
    h = _auth_headers(client)
    r = client.post("/api/compare/blind/vote", headers=h,
                    json={"blind_id": "blind-nope", "winner_label": "A"})
    assert r.status_code == 404
