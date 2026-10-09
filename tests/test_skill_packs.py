"""Skill-pack theme tests: manifests, enable/disable, registry, API."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import backend.skills.packs as packs_mod  # noqa: E402
from backend.skills.packs import (  # noqa: E402
    disable_pack,
    enable_pack,
    enabled_pack_skill_roots,
    get_pack,
    list_packs,
    register_pack_extensions,
)


@pytest.fixture
def pack_state_tmp(tmp_path, monkeypatch):
    """Isolate pack enable/disable state per test."""
    monkeypatch.setattr(packs_mod, "PACK_STATE_FILE", tmp_path / ".pack_state.json")
    import backend.skills.registry as reg_mod

    monkeypatch.setattr(reg_mod, "_registry", None)
    yield tmp_path
    monkeypatch.setattr(reg_mod, "_registry", None)


# --- manifests -------------------------------------------------------------

def test_list_packs_finds_bundled_packs(pack_state_tmp):
    packs = {p.name: p for p in list_packs()}
    assert {"spec-driven", "diagramming", "science-essentials", "agent-loop"} <= set(packs)
    assert packs["spec-driven"].skills == ["sdd-workflow"]
    assert packs["spec-driven"].source == "github/spec-kit"
    assert packs["diagramming"].skills == ["archify"]
    assert set(packs["science-essentials"].skills) == {
        "literature-review", "data-analysis", "citation-hygiene",
    }
    assert packs["agent-loop"].skills == ["tool-discipline"]
    assert all(p.enabled is False for p in packs.values())


def test_get_pack_unknown(pack_state_tmp):
    assert get_pack("no-such-pack") is None
    assert enable_pack("no-such-pack") is None


# --- enable / disable -------------------------------------------------------

def test_enable_disable_roundtrip(pack_state_tmp):
    pack = enable_pack("spec-driven")
    assert pack is not None and pack.enabled is True
    assert get_pack("spec-driven").enabled is True

    pack = disable_pack("spec-driven")
    assert pack.enabled is False
    assert get_pack("spec-driven").enabled is False


def test_enabled_pack_skill_roots(pack_state_tmp):
    assert enabled_pack_skill_roots() == []
    enable_pack("diagramming")
    roots = enabled_pack_skill_roots()
    assert len(roots) == 1 and (roots[0] / "archify" / "SKILL.md").exists()


def test_registry_picks_up_pack_skills(pack_state_tmp):
    from backend.skills.registry import get_registry

    assert "archify" not in get_registry().skills
    enable_pack("diagramming")
    assert "archify" in get_registry().skills
    skill = get_registry().get("archify")
    assert "Mermaid" in skill.description or "mermaid" in skill.prompt_template.lower()
    disable_pack("diagramming")
    assert "archify" not in get_registry().skills


def test_pack_skills_do_not_clobber_user_skills(pack_state_tmp, tmp_path):
    """A user skill with the same id wins over the pack skill."""
    import backend.skills.registry as reg_mod

    user_root = tmp_path / "user_skills" / "archify"
    user_root.mkdir(parents=True)
    (user_root / "SKILL.md").write_text(
        "---\nid: archify\nname: My Archify\ncategory: engineering\n"
        "invocation: both\ndescription: user version\n---\nuser prompt",
        encoding="utf-8",
    )
    pack = get_pack("diagramming")
    reg = reg_mod.SkillRegistry(
        skills_root=tmp_path / "user_skills",
        extra_roots=[pack.skills_root],
    )
    assert reg.get("archify").description == "user version"


def test_pack_extensions_registered(pack_state_tmp):
    from backend.extensions import extensions

    count = register_pack_extensions()
    assert count == 4
    manifest = extensions.get("skill-pack:spec-driven")
    assert manifest is not None and manifest.version == "1.0.0"


# --- API ---------------------------------------------------------------------

def _api_client(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(packs_mod, "PACK_STATE_FILE", tmp_path / ".pack_state.json")
    import backend.skills.registry as reg_mod

    monkeypatch.setattr(reg_mod, "_registry", None)
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    assert "history/sangam.db" not in str(settings.DATABASE_URL)
    reset_engine_for_testing()

    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth(client):
    creds = {"username": "pack_test_user", "password": "StrongPass123!"}
    resp = client.post("/api/auth/register", json=creds)
    data = resp.json() if resp.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def test_packs_api(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    headers = _auth(client)

    resp = client.get("/api/skills/packs", headers=headers)
    assert resp.status_code == 200
    packs = {p["name"]: p for p in resp.json()}
    assert "spec-driven" in packs
    assert packs["spec-driven"]["enabled"] is False

    resp = client.post("/api/skills/packs/spec-driven/enable", headers=headers)
    assert resp.status_code == 200 and resp.json()["enabled"] is True

    # The pack's skill is now listed via the skills API.
    resp = client.get("/api/skills/", params={"q": "sdd"}, headers=headers)
    assert resp.status_code == 200
    assert any(s["id"] == "sdd-workflow" for s in resp.json())

    resp = client.post("/api/skills/packs/spec-driven/disable", headers=headers)
    assert resp.status_code == 200 and resp.json()["enabled"] is False

    resp = client.post("/api/skills/packs/nope/enable", headers=headers)
    assert resp.status_code == 404
