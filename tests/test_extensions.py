"""test_extensions — unified extension system (manifest, registry, API)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# --- Test environment (must run before backend imports) ---------------------
ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "mainfiles")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ["TEST_MODE"] = "1"
# Temp file DB (NullPool + :memory: would lose tables between connections).
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:////tmp/sangam_test_ext_{os.getpid()}.db"
from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("MASTER_KEY", Fernet.generate_key().decode())

import pytest  # noqa: E402
from backend.extensions import (  # noqa: E402
    ExtensionKind,
    ExtensionManifest,
    ExtensionRegistry,
    initialize_extensions,
)
from backend.extensions.registry import extensions  # noqa: E402
from backend.skills.registry import SkillDefinition  # noqa: E402
from backend.tools.schemas import ToolDefinition  # noqa: E402


def _manifest(name: str = "demo", **kwargs) -> ExtensionManifest:
    kwargs.setdefault("version", "1.0.0")
    kwargs.setdefault("kind", ExtensionKind.TOOL)
    return ExtensionManifest(name=name, **kwargs)


# ----------------------------------------------------------------------------
# Manifest semver validation
# ----------------------------------------------------------------------------
class TestManifestSemver:
    @pytest.mark.parametrize(
        "version", ["0.0.1", "1.2.3", "10.20.30", "0.10.0"]
    )
    def test_valid_semver_accepted(self, version: str) -> None:
        manifest = _manifest(version=version)
        assert manifest.version == version
        assert manifest.version_tuple() == tuple(int(p) for p in version.split("."))

    @pytest.mark.parametrize(
        "version",
        ["1.2", "1", "v1.2.3", "1.2.3-beta", "1.2.3+build", "abc", "", "1.2.3.4", "01.2.3"],
    )
    def test_invalid_semver_rejected(self, version: str) -> None:
        with pytest.raises(ValueError):
            _manifest(version=version)

    def test_kind_coerces_from_string(self) -> None:
        manifest = _manifest(kind="skill")
        assert manifest.kind is ExtensionKind.SKILL


# ----------------------------------------------------------------------------
# Registry register / enable / disable roundtrip (isolated state file)
# ----------------------------------------------------------------------------
def _isolated_registry(tmp_path: Path) -> ExtensionRegistry:
    registry = ExtensionRegistry()
    # Exercise the settable state path (fresh state, no cross-test leakage).
    registry.state_path = tmp_path / "extensions_state.json"
    return registry


class TestRegistryRoundtrip:
    def test_register_get_list(self, tmp_path: Path) -> None:
        registry = _isolated_registry(tmp_path)
        registry.register(_manifest("tool:search", description="web search"))
        registry.register(_manifest("skill:debug", kind=ExtensionKind.SKILL))
        assert registry.get("tool:search") is not None
        assert registry.get("missing") is None
        assert {m.name for m in registry.list_all()} == {"tool:search", "skill:debug"}
        assert {m.name for m in registry.list_enabled()} == {"tool:search", "skill:debug"}

    def test_enable_disable_roundtrip(self, tmp_path: Path) -> None:
        registry = _isolated_registry(tmp_path)
        registry.register(_manifest("tool:search"))
        assert registry.is_enabled("tool:search") is True
        assert registry.disable("tool:search") is True
        assert registry.is_enabled("tool:search") is False
        assert [m.name for m in registry.list_enabled()] == []
        assert registry.enable("tool:search") is True
        assert registry.is_enabled("tool:search") is True

    def test_unknown_names(self, tmp_path: Path) -> None:
        registry = _isolated_registry(tmp_path)
        assert registry.enable("nope") is False
        assert registry.disable("nope") is False
        assert registry.is_enabled("nope") is False

    def test_enabled_by_default_false(self, tmp_path: Path) -> None:
        registry = _isolated_registry(tmp_path)
        registry.register(_manifest("tool:beta", enabled_by_default=False))
        assert registry.is_enabled("tool:beta") is False
        registry.enable("tool:beta")
        assert registry.is_enabled("tool:beta") is True

    def test_persistence_roundtrip_across_instances(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        first = ExtensionRegistry()
        first.state_path = state_file
        first.register(_manifest("tool:search"))
        first.register(_manifest("skill:debug"))
        first.disable("tool:search")

        second = ExtensionRegistry(state_path=state_file)
        second.register(_manifest("tool:search"))
        second.register(_manifest("skill:debug"))
        assert second.is_enabled("tool:search") is False
        assert second.is_enabled("skill:debug") is True

    def test_corrupt_state_file_does_not_crash(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text("{not valid json", encoding="utf-8")
        registry = ExtensionRegistry(state_path=state_file)
        registry.register(_manifest("tool:search"))
        assert registry.is_enabled("tool:search") is True


# ----------------------------------------------------------------------------
# Tool / skill adapters
# ----------------------------------------------------------------------------
class TestAdapters:
    def test_tool_adapter_naming(self, tmp_path: Path) -> None:
        registry = _isolated_registry(tmp_path)
        tool = ToolDefinition(
            name="web_search", description="Search the web", parameters={}
        )
        manifest = registry.register_tool_definition(tool)
        assert manifest.name == "tool:web_search"
        assert manifest.kind is ExtensionKind.TOOL
        assert manifest.description == "Search the web"
        # Re-registering overwrites, no duplicates.
        registry.register_tool_definition(tool)
        assert len(registry.list_all()) == 1

    def test_skill_adapter_naming(self, tmp_path: Path) -> None:
        registry = _isolated_registry(tmp_path)
        skill = SkillDefinition(
            id="debugging",
            name="Debugging",
            category="engineering",
            invocation="both",
            description="Debug code",
        )
        manifest = registry.register_skill_definition(skill)
        assert manifest.name == "skill:debugging"
        assert manifest.kind is ExtensionKind.SKILL
        assert registry.get("skill:debugging") is manifest

    def test_initialize_extensions_registers_tools_and_skills(self) -> None:
        result = initialize_extensions()
        assert result is extensions
        names = {m.name for m in extensions.list_all()}
        # Builtin tools auto-register on backend.tools import.
        assert "tool:web_search" in names
        assert "tool:read_file" in names
        assert any(n.startswith("skill:") for n in names)


# ----------------------------------------------------------------------------
# HTTP API (FastAPI TestClient against backend.main.create_app)
# ----------------------------------------------------------------------------
class TestExtensionsApi:
    # Safety: per-test tmp SQLite file, never the production DB — same pattern
    # as test_clarification.py. The module-level DATABASE_URL env override is
    # not enough: backend.config.settings is a singleton created by whichever
    # test module imports it first, so we rebind explicitly here.
    PROD_DB_MARKER = "history/sangam.db"

    @pytest.fixture
    def api_client(self, tmp_path):
        from backend.config import settings  # noqa: PLC0415
        from backend.database import Base, get_engine, reset_engine_for_testing  # noqa: PLC0415
        from backend.extensions.registry import extensions as _ext  # noqa: PLC0415
        from backend.main import create_app  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        settings.DATABASE_URL = f"sqlite+aiosqlite:///{tmp_path}/test.db"
        assert self.PROD_DB_MARKER not in str(settings.DATABASE_URL), "SAFETY ABORT"
        reset_engine_for_testing()
        # Isolate extension enable/disable state per test as well.
        _ext.state_path = tmp_path / "extensions_state.json"

        import asyncio  # noqa: PLC0415

        async def _create_all():
            engine = get_engine()
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        asyncio.run(_create_all())

        app = create_app()
        with TestClient(app) as client:
            yield client

    @staticmethod
    def _auth_headers(client) -> dict[str, str]:
        # Single-user local auth: the first test registers, later ones log in.
        creds = {"username": "ext_test_user", "password": "StrongPass123!"}
        resp = client.post("/api/auth/register", json=creds)
        if resp.status_code == 201:
            data = resp.json()
        else:
            resp = client.post("/api/auth/login", json=creds)
            assert resp.status_code == 200, resp.text
            data = resp.json()
        return {
            "Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"],
        }

    def test_list_extensions(self, api_client) -> None:
        headers = self._auth_headers(api_client)
        resp = api_client.get("/api/extensions", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "extensions" in data
        by_name = {e["name"]: e for e in data["extensions"]}
        assert "tool:web_search" in by_name
        entry = by_name["tool:web_search"]
        assert entry["kind"] == "tool"
        assert entry["version"] == "1.0.0"
        assert entry["enabled"] is True

    def test_toggle_roundtrip(self, api_client) -> None:
        headers = self._auth_headers(api_client)
        # Disable then re-enable the same extension, leaving no persisted delta.
        resp = api_client.post(
            "/api/extensions/tool:web_search/disable", headers=headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"name": "tool:web_search", "enabled": False}

        listed = api_client.get("/api/extensions", headers=headers)
        by_name = {e["name"]: e for e in listed.json()["extensions"]}
        assert by_name["tool:web_search"]["enabled"] is False

        resp = api_client.post(
            "/api/extensions/tool:web_search/enable", headers=headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"name": "tool:web_search", "enabled": True}

    def test_toggle_unknown_returns_404(self, api_client) -> None:
        headers = self._auth_headers(api_client)
        resp = api_client.post("/api/extensions/bogus:thing/enable", headers=headers)
        assert resp.status_code == 404
