"""
api_routes/skills_v2_routes.py — Batch 5 skill-system endpoints.

Registers onto the existing skills router (from skills/api_skills.py),
so no main.py change is needed — api.py imports this module and the
skills router is already mounted at /api/skills.

  POST /skills/install            {source, version?} — hash-verified install + auto-scan
  POST /skills/install/dry-run    {source} — preview files+hashes, writes nothing
  POST /skills/verify             recompute lockfile hashes -> OK/MISMATCH per skill
  POST /skills/{name}/scan        server-side supply-chain / injection scan
  GET  /skills/{name}/checks      per-skill checks (frontmatter, links, parse, eval)
  POST /skills/{name}/run         approval-gated script execution (see below)
  POST /skills/packs/{pack}/pin   {version} — record pin in packs-lock.json
  DELETE /skills/packs/{pack}/pin — unpin
  POST /skills/recommend          {stack?} — stack-aware recommendations
  POST /skills/documents/generate {format, title, sections?, rows?} — file download
  (GET /skills/checks, GET /skills/lock and GET /skills/config-audit live
  in api_skills.py, before the GET /{sid} route, so they are not shadowed
  by it — FastAPI matches routes in registration order.)

Script execution approval flow (reuses the code agent's exact gate):
  1. POST /skills/{name}/run {script, args} -> 202 {status:
     "approval_needed", approval_id}
  2. POST /api/agent/approve/{approval_id} {approved: true}
     (the existing code-agent approval endpoint)
  3. POST /skills/{name}/run {approval_id} -> runs the script.
  Scripts run with python3 (venv interpreter) or bash only, inside a
  fresh temp cwd, with a 60s timeout and captured stdout/stderr.
  Scripts outside the skill dir, absolute-path escapes, and other
  interpreters are rejected. A hash MISMATCH blocks execution (403)
  until the skill is re-installed.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from ..code_agent import create_approval_gate
from ..skills.api_skills import router
from ..skills.docgen import EXTENSIONS, MEDIA_TYPES, generate_document
from ..skills.recommend import recommend as recommend_skills
from ..skills.registry import get_registry
from ..skills.scan import scan_skill_dir
from ..skills.verify import (
    assert_hash_ok,
    dry_run_install,
    find_skill_dir,
    install_skill,
    pin_pack,
    run_skill_checks,
    verify_lock,
)

# approval_id -> gate dict created by code_agent.create_approval_gate
_pending_skill_runs: dict[str, dict] = {}

_RUN_TIMEOUT_S = 60


class InstallIn(BaseModel):
    source: str
    version: str = "1.0.0"


class RunIn(BaseModel):
    script: str | None = None
    args: list[str] = Field(default_factory=list)
    approval_id: str | None = None


class PinIn(BaseModel):
    version: str


class RecommendIn(BaseModel):
    stack: list[str] | None = None


class DocGenIn(BaseModel):
    format: str
    title: str = "Untitled"
    sections: list[dict] = Field(default_factory=list)
    rows: list[list] = Field(default_factory=list)


def _skill_dir_or_404(name: str) -> Path:
    skill_dir = find_skill_dir(name)
    if skill_dir is None:
        raise HTTPException(404, f"Skill not found: {name}")
    return skill_dir


def _resolve_script(skill_dir: Path, requested: str | None) -> Path:
    scripts_dir = skill_dir / "scripts"
    if requested:
        if Path(requested).is_absolute() or ".." in Path(requested).parts:
            raise HTTPException(400, "Script path escapes the skill directory")
        candidate = (scripts_dir / requested).resolve()
        root = scripts_dir.resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise HTTPException(404, f"Script not found in skill: {requested}")
        return candidate
    if not scripts_dir.exists():
        raise HTTPException(404, "Skill has no scripts/ directory")
    for p in sorted(scripts_dir.iterdir()):
        if p.is_file() and p.suffix in (".py", ".sh"):
            return p
    raise HTTPException(404, "Skill has no runnable script")


@router.post("/install")
async def install_skill_endpoint(payload: InstallIn):
    source = Path(payload.source)
    if not source.is_dir():
        raise HTTPException(404, f"Install source not found: {payload.source}")
    try:
        result = install_skill(source, version=payload.version)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    skill_dir = find_skill_dir(result["name"])
    scan = scan_skill_dir(skill_dir) if skill_dir else {"findings": []}
    return {**result, "scan": scan}


@router.post("/install/dry-run")
async def install_dry_run(payload: InstallIn):
    try:
        return dry_run_install(Path(payload.source))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/verify")
async def verify_skills_endpoint():
    return {"skills": verify_lock()}


@router.post("/{name}/scan")
async def scan_skill_endpoint(name: str):
    return scan_skill_dir(_skill_dir_or_404(name))


@router.get("/{name}/checks")
async def skill_checks_endpoint(name: str):
    return run_skill_checks(_skill_dir_or_404(name))


@router.post("/{name}/run")
async def run_skill_script(name: str, payload: RunIn):
    skill_dir = _skill_dir_or_404(name)
    ok, reason = assert_hash_ok(name)
    if not ok:
        raise HTTPException(403, reason)
    script = _resolve_script(skill_dir, payload.script)
    if len(payload.args) > 50 or any(len(a) > 500 for a in payload.args):
        raise HTTPException(400, "Too many or too long script arguments")
    if payload.approval_id:
        gate = _pending_skill_runs.get(payload.approval_id)
        if gate is None:
            raise HTTPException(404, "Approval not found or expired")
        if gate["decision"] is None:
            return JSONResponse(status_code=202, content={
                "status": "approval_needed", "approval_id": payload.approval_id})
        _pending_skill_runs.pop(payload.approval_id, None)
        if gate["decision"] is not True:
            raise HTTPException(403, "Script run denied by user")
    else:
        import uuid as _uuid
        approval_id = f"skill-appr-{_uuid.uuid4().hex[:12]}"
        gate = create_approval_gate(approval_id)
        _pending_skill_runs[approval_id] = gate
        return JSONResponse(status_code=202, content={
            "status": "approval_needed", "approval_id": approval_id,
            "script": script.name, "args": payload.args})
    if script.suffix == ".py":
        cmd = [sys.executable, str(script)]
    elif script.suffix == ".sh":
        bash = shutil.which("bash")
        if not bash:
            raise HTTPException(500, "bash not available")
        cmd = [bash, str(script)]
    else:
        raise HTTPException(400, f"Unsupported script interpreter for {script.suffix}")
    tmp = tempfile.mkdtemp(prefix="sangam-skill-run-")
    try:
        result = subprocess.run(cmd + list(payload.args), cwd=tmp,
                                capture_output=True, text=True,
                                timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "Script timed out")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"status": "ok", "script": script.name, "returncode": result.returncode,
            "stdout": result.stdout[:8000], "stderr": result.stderr[:8000]}


@router.post("/packs/{pack}/pin")
async def pin_pack_endpoint(pack: str, payload: PinIn):
    from ..skills.packs import get_pack
    if get_pack(pack) is None:
        raise HTTPException(404, f"Skill pack not found: {pack}")
    pin_pack(pack, payload.version)
    return {"pack": pack, "pinned_version": payload.version}


@router.delete("/packs/{pack}/pin")
async def unpin_pack_endpoint(pack: str):
    from ..skills.packs import get_pack
    if get_pack(pack) is None:
        raise HTTPException(404, f"Skill pack not found: {pack}")
    pin_pack(pack, None)
    return {"pack": pack, "pinned_version": None}


@router.post("/recommend")
async def recommend_endpoint(payload: RecommendIn):
    workspace_root = Path.cwd()
    try:
        from ..tools.builtin import _get_workspace_root
        workspace_root = _get_workspace_root()
    except Exception:  # noqa: BLE001 — fall back to cwd
        pass
    try:
        installed = set(get_registry().skills.keys())
    except Exception:  # noqa: BLE001
        installed = set()
    return recommend_skills(stack=payload.stack,
                            workspace_root=workspace_root,
                            installed_ids=installed)


@router.post("/documents/generate")
async def generate_document_endpoint(payload: DocGenIn):
    fmt = (payload.format or "").lower()
    if fmt not in EXTENSIONS:
        raise HTTPException(400, f"Unsupported format: {payload.format}")
    try:
        data = generate_document(fmt, payload.title,
                                 sections=payload.sections, rows=payload.rows)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    safe_title = "".join(c if c.isalnum() or c in "-_" else "-" for c in payload.title)[:80] or "document"
    return Response(
        content=data, media_type=MEDIA_TYPES[fmt],
        headers={"Content-Disposition":
                 f'attachment; filename="{safe_title}.{EXTENSIONS[fmt]}"'})
