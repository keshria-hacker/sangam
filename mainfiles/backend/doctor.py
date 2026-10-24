"""Doctor endpoint module for the agent subsystem (deep-read Wave 1).

ECC's ``doctor.js`` pattern, ported: a self-audit of the harness itself
rather than of the user's code. ``GET /api/system/doctor`` reports one
check per subsystem — providers, keys, skill packs, workspace, MCP
servers, automations — each with a status and, where unhealthy, a fix
hint telling the operator exactly what to do.

MODULE ONLY — this router is intentionally NOT registered in ``api.py``.
The parent wires it in (``app.include_router(doctor_router)`` or the
shared ``/api`` router). Keeping it unregistered here means no other
worker's route table changes, and tests can mount it on a throwaway app.

Privacy: the response contains presence/counts only. It never contains
a key value, a token, or file contents. Mounting note for the parent:
consider putting this router behind the host/admin auth used by the
other ``/system/*`` routes; the module itself takes no auth dependency
so it stays mountable in tests without a user fixture.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import get_db

router = APIRouter()


def _check(name: str, status: str, detail: str = "",
           fix_hint: str | None = None) -> dict[str, Any]:
    check: dict[str, Any] = {"name": name, "status": status, "detail": detail}
    if fix_hint:
        check["fix_hint"] = fix_hint
    return check


def _overall(checks: list[dict[str, Any]]) -> str:
    statuses = [c["status"] for c in checks]
    if "error" in statuses:
        return "error"
    if "warn" in statuses:
        return "warn"
    if "unknown" in statuses:
        return "unknown"
    return "ok"


async def _db_checks(db: Any) -> list[dict[str, Any]]:
    """Provider-key and automation checks. Degrade to unknown, never 500."""
    checks: list[dict[str, Any]] = []
    if db is None:
        return [
            _check("providers", "unknown", "No database session available.",
                   "Restart the server; if this persists, check DATABASE_URL."),
            _check("keys", "unknown", "No database session available.",
                   "Restart the server; if this persists, check DATABASE_URL."),
            _check("automations", "unknown", "No database session available.",
                   "Restart the server; if this persists, check DATABASE_URL."),
        ]
    try:
        from sqlalchemy import select

        from .models import Automation, ProviderKey
        key_rows = (await db.execute(select(ProviderKey.provider_id))).all()
        key_providers = sorted({row[0] for row in key_rows})
        auto_rows = (await db.execute(
            select(Automation.id, Automation.enabled))).all()
        enabled = sum(1 for row in auto_rows if row[1])
        try:
            from .providers import list_providers_static
            known = list_providers_static()
            configured = [p for p in key_providers if p in known]
            unknown_providers = [p for p in key_providers if p not in known]
        except Exception:  # noqa: BLE001 — static list is best-effort
            known, configured, unknown_providers = {}, key_providers, []
        if not key_providers:
            checks.append(_check(
                "keys", "warn", "No provider keys configured.",
                "Add a provider key in Settings > Providers so the agent "
                "can call a model."))
        else:
            detail = f"{len(key_providers)} provider key(s) configured"
            if configured:
                detail += f": {', '.join(configured)}"
            if unknown_providers:
                detail += f"; unrecognized: {', '.join(unknown_providers)}"
            checks.append(_check("keys", "ok", detail))
        checks.append(_check(
            "providers", "ok" if key_providers else "warn",
            f"{len(known)} known providers; "
            f"{len(configured)} with a stored key."
            if known else f"{len(key_providers)} provider key(s) stored.",
            None if key_providers else
            "Add a provider key in Settings > Providers."))
        checks.append(_check(
            "automations", "ok",
            f"{len(auto_rows)} automation(s), {enabled} enabled."))
    except Exception as exc:  # noqa: BLE001 — doctor never 500s
        checks.extend([
            _check("providers", "unknown", f"Could not read providers: {exc}",
                   "Check the server log and DATABASE_URL."),
            _check("keys", "unknown", f"Could not read keys: {exc}",
                   "Check the server log and DATABASE_URL."),
            _check("automations", "unknown",
                   f"Could not read automations: {exc}",
                   "Check the server log and DATABASE_URL."),
        ])
    return checks


def _local_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    # Workspace
    try:
        root = settings.WORKSPACE_ROOT
        exists = root.exists()
        writable = os.access(root, os.W_OK) if exists else False
        if exists and writable:
            checks.append(_check("workspace", "ok", f"Workspace root {root} "
                                 "exists and is writable."))
        elif exists:
            checks.append(_check(
                "workspace", "error", f"Workspace root {root} is not writable.",
                "Fix permissions on the workspace directory, or set "
                "WORKSPACE_ROOT to a writable directory and restart."))
        else:
            checks.append(_check(
                "workspace", "error", f"Workspace root {root} does not exist.",
                "Create the directory, or set WORKSPACE_ROOT to an "
                "existing directory and restart."))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("workspace", "unknown",
                             f"Could not inspect workspace: {exc}",
                             "Check WORKSPACE_ROOT in the server configuration."))
    # Skill packs
    try:
        from .skills.packs import enabled_pack_skill_roots
        from .skills.registry import get_registry
        roots = enabled_pack_skill_roots()
        skills = list(get_registry().skills.values())
        if skills:
            checks.append(_check(
                "packs", "ok",
                f"{len(skills)} skill(s) loaded from {len(roots)} "
                "enabled pack root(s)."))
        else:
            checks.append(_check(
                "packs", "warn", "No skills loaded.",
                "Install a skill pack from the Library, or check that "
                "enabled packs still exist on disk."))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("packs", "unknown",
                             f"Could not inspect skill packs: {exc}",
                             "Check the server log; skill loading failed."))
    # MCP servers (configured, not probed — probing would spawn processes)
    try:
        servers = settings.mcp_server_configs()
        if not servers:
            checks.append(_check(
                "mcp_servers", "warn", "No MCP servers configured.",
                "Set MCP_SERVERS_JSON in the server configuration to add "
                "an MCP server, or leave it empty if none are needed."))
        else:
            names = ", ".join(str(s.get("name", "?")) for s in servers)
            checks.append(_check(
                "mcp_servers", "ok",
                f"{len(servers)} MCP server(s) configured: {names}. "
                "Reachability is not probed by doctor."))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("mcp_servers", "unknown",
                             f"Could not parse MCP configuration: {exc}",
                             "Fix MCP_SERVERS_JSON — it must be a JSON list "
                             "of {name, command} objects."))
    return checks


@router.get("/system/doctor")
async def system_doctor(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Self-audit of the agent subsystem. Never 500s; unhealthy checks
    carry fix hints. DB-backed checks degrade to 'unknown' when the
    session cannot be read."""
    checks = await _db_checks(db)
    checks.extend(_local_checks())
    return {"status": _overall(checks), "checks": checks}
