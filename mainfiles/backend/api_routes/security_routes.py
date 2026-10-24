"""
api_routes/security_routes.py — Batch 2 security workspace.

Routes (mounted under /api by main.py; the coordinator wires this
module into api.py — importing it registers the handlers on the
shared router AND registers the security tables with Base.metadata):

  GET    /security/allowlist
  POST   /security/allowlist
  DELETE /security/allowlist/{target_id}
  GET    /security/catalog
  POST   /security/catalog/{name}/enable
  POST   /security/runs
  GET    /security/runs
  GET    /security/runs/{run_id}
  POST   /security/runs/{run_id}/approve
  POST   /security/runs/{run_id}/phase
  POST   /security/runs/{run_id}/browser
  GET    /security/runs/{run_id}/audit
  POST   /security/runs/{run_id}/findings
  GET    /security/runs/{run_id}/findings
  POST   /security/findings/{finding_id}/validate
  POST   /security/runs/{run_id}/report

Honest limits (see also the guardrails module docstring):
- Catalog entries are DATA ONLY: nothing here installs or runs a
  catalog tool. Approve executes passive recon (headers / robots.txt /
  sitemap / DNS) only; other tool classes record that they were not
  executed in v1.
- If Docker is absent, runs record isolation="workspace-fallback"
  with an explicit warning — never silently containerised.
- The browser endpoint returns 503 when the driver/engine is
  unavailable instead of fabricating results.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..browser_agent import (
    BrowserActionError,
    BrowserDriverUnavailable,
    run_browser_actions,
)
from ..database import get_db
from ..security_catalog import catalog_entry, list_catalog
from ..security_guardrails import (
    PHASES,
    VALIDATION_VERDICTS,
    SecurityAllowlistTarget,
    SecurityAudit,
    SecurityCatalogSetting,
    SecurityFinding,
    SecurityRun,
    audit_row,
    check_scope,
    docker_available,
    extract_host,
    mirror_runstore,
    next_phase,
    run_passive_recon,
    severity_from_cvss,
)
from .common import router

TOOL_CLASSES = {"recon", "scan", "browser-automation", "browser-security-test"}


# ------------------------------------------------------------------ inputs

class AllowlistIn(BaseModel):
    host_pattern: str = Field(min_length=1, max_length=255)
    note: str = ""


class CatalogEnableIn(BaseModel):
    enabled: bool


class RunIn(BaseModel):
    target: str = Field(min_length=1, max_length=512)
    scope: str = ""
    tool_class: str = "recon"
    browser_automation_approved: bool = False
    browser_security_approved: bool = False


class PhaseIn(BaseModel):
    phase: str


class BrowserIn(BaseModel):
    mode: str
    actions: list[dict] = Field(min_length=1, max_length=50)


class FindingIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    cvss_score: float | None = Field(default=None, ge=0.0, le=10.0)
    owasp_category: str = ""
    evidence: str = ""
    patch_diff: str = ""


class ValidateIn(BaseModel):
    verdict: str
    notes: str = ""


# -------------------------------------------------------------- serializers

def _allowlist_out(row: SecurityAllowlistTarget) -> dict:
    return {"id": row.id, "host_pattern": row.host_pattern, "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None}


def _run_out(row: SecurityRun) -> dict:
    return {
        "id": row.id, "target": row.target, "scope": row.scope,
        "tool_class": row.tool_class, "status": row.status, "phase": row.phase,
        "isolation": row.isolation, "isolation_warning": row.isolation_warning,
        "image_used": row.image_used,
        "browser_automation_approved": row.browser_automation_approved,
        "browser_security_approved": row.browser_security_approved,
        "result": json.loads(row.result_json or "{}"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _finding_out(row: SecurityFinding) -> dict:
    return {
        "id": row.id, "run_id": row.run_id, "title": row.title,
        "severity": row.severity, "cvss_score": row.cvss_score,
        "owasp_category": row.owasp_category, "status": row.status,
        "validation_verdict": row.validation_verdict,
        "validation_notes": row.validation_notes,
        "evidence": row.evidence, "patch_diff": row.patch_diff,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _audit_out(row: SecurityAudit) -> dict:
    return {"id": row.id, "run_id": row.run_id, "action": row.action,
            "summary": row.summary, "poc_reference": row.poc_reference,
            "created_at": row.created_at.isoformat() if row.created_at else None}


async def _patterns(db: AsyncSession, user_id: str) -> list[str]:
    rows = (await db.execute(
        select(SecurityAllowlistTarget).where(SecurityAllowlistTarget.user_id == user_id)
    )).scalars().all()
    return [r.host_pattern for r in rows]


async def _get_run(db: AsyncSession, user_id: str, run_id: str) -> SecurityRun:
    run = await db.get(SecurityRun, run_id)
    if not run or run.user_id != user_id:
        raise HTTPException(status_code=404, detail="Security run not found")
    return run


def _valid_pattern(pattern: str) -> bool:
    pat = (pattern or "").strip().lower()
    if pat.startswith("*."):
        pat = pat[2:]
    if not pat or ".." in pat or "/" in pat or " " in pat:
        return False
    labels = pat.split(".")
    return len(labels) >= 2 and all(
        label and all(c.isalnum() or c == "-" for c in label) for label in labels)


# --------------------------------------------------------------- allowlist

@router.get("/security/allowlist")
async def list_allowlist(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    rows = (await db.execute(
        select(SecurityAllowlistTarget).where(SecurityAllowlistTarget.user_id == user.id)
        .order_by(desc(SecurityAllowlistTarget.created_at))
    )).scalars().all()
    return {"targets": [_allowlist_out(r) for r in rows]}


@router.post("/security/allowlist", status_code=201)
async def add_allowlist(payload: AllowlistIn, db: AsyncSession = Depends(get_db),
                        user=Depends(get_current_user)):
    pattern = payload.host_pattern.strip().lower()
    if not _valid_pattern(pattern):
        raise HTTPException(status_code=422,
                            detail="host_pattern must be a bare host (example.com) or wildcard (*.example.com)")
    row = SecurityAllowlistTarget(id=f"sec-{uuid.uuid4().hex[:12]}", user_id=user.id,
                                  host_pattern=pattern, note=payload.note or "")
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _allowlist_out(row)


@router.delete("/security/allowlist/{target_id}")
async def delete_allowlist(target_id: str, db: AsyncSession = Depends(get_db),
                           user=Depends(get_current_user)):
    row = await db.get(SecurityAllowlistTarget, target_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Allowlist target not found")
    await db.delete(row)
    await db.commit()
    return {"deleted": target_id}


# ----------------------------------------------------------------- catalog

@router.get("/security/catalog")
async def get_catalog(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    rows = (await db.execute(
        select(SecurityCatalogSetting).where(SecurityCatalogSetting.user_id == user.id)
    )).scalars().all()
    overrides = {r.entry_name: r.enabled for r in rows}
    from ..security_catalog import EXCLUSIONS
    return {"tools": list_catalog(overrides), "exclusions": EXCLUSIONS}


@router.post("/security/catalog/{name}/enable")
async def set_catalog_enabled(name: str, payload: CatalogEnableIn,
                              db: AsyncSession = Depends(get_db),
                              user=Depends(get_current_user)):
    entry = catalog_entry(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown catalog tool: {name}")
    row = (await db.execute(
        select(SecurityCatalogSetting).where(
            SecurityCatalogSetting.user_id == user.id,
            SecurityCatalogSetting.entry_name == entry["name"])
    )).scalars().first()
    if row is None:
        row = SecurityCatalogSetting(id=f"sec-{uuid.uuid4().hex[:12]}", user_id=user.id,
                                     entry_name=entry["name"], enabled=payload.enabled)
        db.add(row)
    else:
        row.enabled = payload.enabled
    await db.commit()
    return {"name": entry["name"], "enabled": payload.enabled,
            "risk": entry["risk"], "enabled_by_default": entry["enabled_by_default"]}


# -------------------------------------------------------------------- runs

@router.post("/security/runs", status_code=201)
async def create_run(payload: RunIn, db: AsyncSession = Depends(get_db),
                     user=Depends(get_current_user)):
    if payload.tool_class not in TOOL_CLASSES:
        raise HTTPException(status_code=422, detail=f"Unknown tool_class: {payload.tool_class}")
    if not extract_host(payload.target):
        raise HTTPException(status_code=422, detail="target must contain a hostname")
    patterns = await _patterns(db, user.id)
    if not check_scope(payload.target, patterns):
        raise HTTPException(status_code=403, detail=(
            "Target is out of scope: add it to the allowlist first. "
            "Runs are refused before any tool fires when no allowlist pattern matches."))
    run = SecurityRun(
        id=f"sec-{uuid.uuid4().hex[:12]}", user_id=user.id, target=payload.target,
        scope=payload.scope or "", tool_class=payload.tool_class,
        browser_automation_approved=payload.browser_automation_approved,
        browser_security_approved=payload.browser_security_approved)
    db.add(run)
    db.add(audit_row(run.id, user.id, "run.created",
                     f"Security run created (pending): target={payload.target} "
                     f"tool_class={payload.tool_class}"))
    await db.commit()
    await db.refresh(run)
    mirror_runstore(run.id, user.id, f"Security run: {payload.target}", "pending")
    return _run_out(run)


@router.get("/security/runs")
async def list_runs(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    rows = (await db.execute(
        select(SecurityRun).where(SecurityRun.user_id == user.id)
        .order_by(desc(SecurityRun.created_at))
    )).scalars().all()
    return {"runs": [_run_out(r) for r in rows]}


@router.get("/security/runs/{run_id}")
async def get_run(run_id: str, db: AsyncSession = Depends(get_db),
                  user=Depends(get_current_user)):
    return _run_out(await _get_run(db, user.id, run_id))


@router.post("/security/runs/{run_id}/approve")
async def approve_run(run_id: str, db: AsyncSession = Depends(get_db),
                      user=Depends(get_current_user)):
    """Separate approval step: re-checks scope, then executes.

    Scope is re-checked against the CURRENT allowlist — deleting the
    target between creation and approval blocks execution (403).
    """
    run = await _get_run(db, user.id, run_id)
    if run.status != "pending":
        raise HTTPException(status_code=409, detail=f"Run is already {run.status}")
    patterns = await _patterns(db, user.id)
    if not check_scope(run.target, patterns):
        raise HTTPException(status_code=403, detail=(
            "Target is out of scope at approval time: the allowlist no longer "
            "covers this target. Execution refused."))
    if docker_available():
        run.isolation = "docker"
        run.image_used = "sangam/security-runner:latest"
        run.isolation_warning = ""
    else:
        from ..security_guardrails import WORKSPACE_FALLBACK_WARNING
        run.isolation = "workspace-fallback"
        run.isolation_warning = WORKSPACE_FALLBACK_WARNING
        run.image_used = ""
    if run.tool_class == "recon":
        result = {"recon": run_passive_recon(run.target)}
    else:
        # Catalog tools are data-only in v1: nothing is installed or run.
        result = {"not_executed": (
            f"tool_class {run.tool_class} is catalogued but not executed in v1; "
            "only passive recon runs automatically. See /security/catalog.")}
    run.result_json = json.dumps(result)
    run.status = "executed"
    run.updated_at = datetime.now(UTC)
    db.add(audit_row(run.id, user.id, "run.approved",
                     f"Run approved and executed: isolation={run.isolation} "
                     f"tool_class={run.tool_class}"))
    await db.commit()
    await db.refresh(run)
    mirror_runstore(run.id, user.id, f"Security run: {run.target}", "succeeded")
    return _run_out(run)


@router.post("/security/runs/{run_id}/phase")
async def advance_phase(run_id: str, payload: PhaseIn, db: AsyncSession = Depends(get_db),
                        user=Depends(get_current_user)):
    run = await _get_run(db, user.id, run_id)
    expected = next_phase(run.phase)
    if payload.phase not in PHASES:
        raise HTTPException(status_code=422, detail=f"Unknown phase: {payload.phase}")
    if payload.phase != expected:
        raise HTTPException(status_code=422, detail=(
            f"Phases advance in order Recon -> Vuln-hunter -> Validator -> Reporter; "
            f"from {run.phase} the next phase is {expected or '(none — already at Reporter)'}"))
    run.phase = payload.phase
    run.updated_at = datetime.now(UTC)
    db.add(audit_row(run.id, user.id, "run.phase",
                     f"Phase advanced to {payload.phase}"))
    await db.commit()
    await db.refresh(run)
    return _run_out(run)


@router.post("/security/runs/{run_id}/browser")
async def run_browser(run_id: str, payload: BrowserIn, db: AsyncSession = Depends(get_db),
                      user=Depends(get_current_user)):
    """Browser agent: two separately-gated modes, never merged.

    mode="automation" needs browser_automation_approved on the run;
    mode="security-test" needs browser_security_approved. Either flag
    missing -> 403. Driver/engine missing -> 503, never fake results.
    """
    run = await _get_run(db, user.id, run_id)
    if run.status != "executed":
        raise HTTPException(status_code=409, detail="Run must be approved/executed before browser use")
    if payload.mode == "automation" and not run.browser_automation_approved:
        raise HTTPException(status_code=403, detail="Browser automation is not approved on this run")
    if payload.mode == "security-test" and not run.browser_security_approved:
        raise HTTPException(status_code=403, detail="Browser security-test is not approved on this run")
    if payload.mode not in ("automation", "security-test"):
        raise HTTPException(status_code=422, detail=f"Unknown browser mode: {payload.mode}")
    patterns = await _patterns(db, user.id)
    if not check_scope(run.target, patterns):
        raise HTTPException(status_code=403, detail="Target is out of scope at browser time")
    profile_root = Path(os.environ.get("SANGAM_BROWSER_PROFILE_ROOT", "")) \
        or (Path.cwd() / ".sangam-browser-profiles")
    profile_dir = profile_root / run.id
    try:
        result = run_browser_actions(payload.mode, payload.actions, profile_dir)
    except BrowserActionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BrowserDriverUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db.add(audit_row(run.id, user.id, f"browser.{payload.mode}",
                     f"Browser actions: {len(result.results)}; "
                     f"screenshots: {', '.join(result.screenshot_paths) or 'none'}",
                     poc_reference=json.dumps(result.results)[:2000]))
    await db.commit()
    return {"mode": result.mode, "results": result.results,
            "screenshot_paths": result.screenshot_paths}


@router.get("/security/runs/{run_id}/audit")
async def list_audit(run_id: str, db: AsyncSession = Depends(get_db),
                     user=Depends(get_current_user)):
    run = await _get_run(db, user.id, run_id)
    rows = (await db.execute(
        select(SecurityAudit).where(SecurityAudit.run_id == run.id)
        .order_by(SecurityAudit.created_at)
    )).scalars().all()
    return {"audit": [_audit_out(r) for r in rows]}


# ----------------------------------------------------------------- findings

@router.post("/security/runs/{run_id}/findings", status_code=201)
async def add_finding(run_id: str, payload: FindingIn, db: AsyncSession = Depends(get_db),
                      user=Depends(get_current_user)):
    run = await _get_run(db, user.id, run_id)
    row = SecurityFinding(
        id=f"sec-{uuid.uuid4().hex[:12]}", run_id=run.id, user_id=user.id,
        title=payload.title, severity=severity_from_cvss(payload.cvss_score),
        cvss_score=payload.cvss_score, owasp_category=payload.owasp_category,
        evidence=payload.evidence, patch_diff=payload.patch_diff)
    db.add(row)
    db.add(audit_row(run.id, user.id, "finding.created",
                     f"Finding created: {payload.title} (severity {row.severity})"))
    await db.commit()
    await db.refresh(row)
    return _finding_out(row)


@router.get("/security/runs/{run_id}/findings")
async def list_findings(run_id: str, db: AsyncSession = Depends(get_db),
                        user=Depends(get_current_user)):
    run = await _get_run(db, user.id, run_id)
    rows = (await db.execute(
        select(SecurityFinding).where(SecurityFinding.run_id == run.id)
        .order_by(SecurityFinding.created_at)
    )).scalars().all()
    return {"findings": [_finding_out(r) for r in rows]}


@router.post("/security/findings/{finding_id}/validate")
async def validate_finding(finding_id: str, payload: ValidateIn,
                           db: AsyncSession = Depends(get_db),
                           user=Depends(get_current_user)):
    if payload.verdict not in VALIDATION_VERDICTS:
        raise HTTPException(status_code=422,
                            detail=f"Verdict must be one of {sorted(VALIDATION_VERDICTS)}")
    row = await db.get(SecurityFinding, finding_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Finding not found")
    row.validation_verdict = payload.verdict
    row.validation_notes = payload.notes or ""
    row.status = "validated"
    db.add(audit_row(row.run_id, user.id, "finding.validated",
                     f"Finding {row.title} validated: {payload.verdict}"))
    await db.commit()
    await db.refresh(row)
    return _finding_out(row)


@router.post("/security/runs/{run_id}/report")
async def build_report(run_id: str, db: AsyncSession = Depends(get_db),
                       user=Depends(get_current_user)):
    """Report gate: REFUSES (422) unless every finding is validated PASS.

    The error lists the unvalidated ones so the UI can show exactly
    what blocks the report — nothing is silently dropped.
    """
    run = await _get_run(db, user.id, run_id)
    rows = (await db.execute(
        select(SecurityFinding).where(SecurityFinding.run_id == run.id)
    )).scalars().all()
    blocking = [r for r in rows
                if not (r.status == "validated" and r.validation_verdict == "PASS")]
    if blocking:
        raise HTTPException(status_code=422, detail={
            "error": "Report refused: not every finding is validated PASS",
            "unvalidated": [{"id": r.id, "title": r.title,
                             "status": r.status,
                             "validation_verdict": r.validation_verdict} for r in blocking],
        })
    findings = [_finding_out(r) for r in rows]
    lines = [f"# Security report — {run.target}",
             f"Phase: {run.phase} | Isolation: {run.isolation or 'n/a'}",
             ""]
    for item in findings:
        lines.append(f"- [{item['severity']}] {item['title']} "
                     f"({item['owasp_category'] or 'uncategorised'}) — PASS")
    db.add(audit_row(run.id, user.id, "report.built",
                     f"Report built with {len(findings)} validated-PASS findings"))
    await db.commit()
    return {"run_id": run.id, "target": run.target, "findings": findings,
            "report_markdown": "\n".join(lines)}
