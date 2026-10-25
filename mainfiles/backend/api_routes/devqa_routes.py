"""api_routes/devqa_routes.py — Batch 12: Dev / QA / Security / Platform.

One route family for the four combined surfaces in qa/devqa.py. Every
endpoint is authenticated (shared router); nothing here executes a VM,
installs a tool, runs a Windows tweak, sends an external push, or
launches an autonomous pentest. Persistence for services / health
history / notifications / folders / presets is the SQLite sidecar in
qa/devqa.py (uploads/devqa.db, SANGAM_DEVQA_DB override for tests) —
single-user, no new shared-model tables, so parallel batches sharing
models.py are untouched.

Excluded categories are rejected at the route (security/categories),
not just hidden in UI. Generated pytest code is returned for review
and never written to tests/ by any endpoint here.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, UTC
from typing import Any

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import Workflow, WorkflowRun
from ..qa import devqa
from ..workflows import WorkflowError, run_workflow_row, validate_definition
from .common import router


# ---------------------------------------------------------------- helpers

def _conn() -> sqlite3.Connection:
    path = devqa.ensure_store()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _svc_out(row) -> dict:
    return {"id": row["id"], "name": row["name"], "url": row["url"],
            "created_at": row["created_at"]}


class AnyIn(BaseModel):
    model_config = {"extra": "allow"}

    def data(self) -> dict:
        return self.model_dump(exclude_none=False)


def _payload(payload: AnyIn) -> dict:
    return payload.model_dump()


# ---------------------------------------------------------------- workflows

@router.get("/devqa/node-catalogue")
async def get_node_catalogue(user=Depends(get_current_user)):
    """Typed node catalogue (langflow contract shape, Sangam node set)."""
    return {"nodes": devqa.node_catalogue(),
            "notes": ["Fan-out is DAG edges (one node feeding several downstream nodes).",
                      "A sub-flow is a workflow run referenced by id; no fake subflow node type exists."]}


@router.get("/devqa/workflow-templates")
async def list_workflow_templates(user=Depends(get_current_user)):
    return {"templates": [devqa.workflow_template(n) for n in ("chatbot", "agent", "workflow")]}


@router.get("/devqa/workflow-templates/{name}")
async def get_workflow_template(name: str, user=Depends(get_current_user)):
    tpl = devqa.workflow_template(name)
    if tpl is None:
        raise HTTPException(status_code=404, detail=f"unknown template: {name}")
    return tpl


@router.post("/devqa/workflows/validate")
async def validate_workflow(payload: AnyIn, user=Depends(get_current_user)):
    """Strict validation: engine validation + variable-pool scoping.
    Unresolved {{nodes.missing.x}} / unknown scopes are errors here,
    even though the engine renders unknown keys as '' at runtime."""
    definition = payload.data().get("definition") or {}
    errors: list[str] = []
    try:
        validate_definition(definition)
    except WorkflowError as exc:
        errors.append(str(exc))
    errors.extend(devqa.validate_template_variables(definition))
    return {"valid": not errors, "errors": errors}


class ResumeIn(BaseModel):
    human_input: dict = Field(default_factory=dict)


@router.post("/devqa/workflows/{workflow_id}/runs/{run_id}/resume", status_code=201)
async def resume_workflow_run(workflow_id: str, run_id: str, payload: ResumeIn,
                              db: AsyncSession = Depends(get_db),
                              user=Depends(get_current_user)):
    """Resume an awaiting_input run. Creates a NEW run (replay_of = the
    paused run) with the submitted values merged into the original
    input — the workflow replays from the start, so non-idempotent
    nodes (e.g. llm) re-run. That limitation is stated, not hidden."""
    wf = (await db.execute(select(Workflow).where(
        Workflow.id == workflow_id, Workflow.user_id == user.id))).scalars().first()
    if wf is None:
        raise HTTPException(status_code=404, detail="workflow not found")
    old = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.id == run_id, WorkflowRun.workflow_id == workflow_id))).scalars().first()
    if old is None:
        raise HTTPException(status_code=404, detail="run not found")
    if old.status != "awaiting_input":
        raise HTTPException(status_code=422, detail=f"run is {old.status}, not awaiting_input")
    already = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.replay_of == run_id))).scalars().first()
    if already is not None:
        raise HTTPException(status_code=422, detail="run was already resumed")
    merged = json.loads(old.input_json or "{}")
    merged_human = dict(merged.get("human_input") or {})
    merged_human.update(payload.human_input)
    merged["human_input"] = merged_human
    new_run = await run_workflow_row(wf, db, merged, replay_of=old.id)
    return {"id": new_run.id, "workflow_id": new_run.workflow_id,
            "status": new_run.status, "replay_of": new_run.replay_of,
            "node_results": json.loads(new_run.node_results_json or "{}"),
            "note": "Resume replays from the original input; non-idempotent nodes re-run."}


# ---------------------------------------------------------------- spec

@router.post("/devqa/spec/constitution/check")
async def check_constitution(payload: AnyIn, user=Depends(get_current_user)):
    d = payload.data()
    return devqa.constitution_check(d.get("plan") or "", d.get("constitution") or "")


@router.post("/devqa/spec/mvp-order")
async def mvp_order(payload: AnyIn, user=Depends(get_current_user)):
    try:
        ordered = devqa.mvp_order(payload.data().get("items") or [])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"mvp_tasks": ordered, "mode": "P1 only"}


# ---------------------------------------------------------------- crawl

@router.post("/devqa/crawl/order")
async def crawl_order(payload: AnyIn, user=Depends(get_current_user)):
    d = payload.data()
    try:
        return {"ordered": devqa.order_frontier(d.get("scored") or [], d.get("strategy") or "bfs")}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/devqa/crawl/filter")
async def crawl_filter(payload: AnyIn, user=Depends(get_current_user)):
    d = payload.data()
    try:
        return {"urls": devqa.apply_filters(d.get("urls") or [], d.get("filters") or [],
                                            d.get("seed_host") or "")}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/devqa/crawl/chunk")
async def crawl_chunk(payload: AnyIn, user=Depends(get_current_user)):
    d = payload.data()
    try:
        return {"chunks": devqa.chunk_markdown(d.get("markdown") or "",
                                               d.get("strategy") or "paragraph",
                                               int(d.get("max_chars") or 1000),
                                               int(d.get("overlap") or 100))}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/devqa/crawl/link-graph")
async def crawl_link_graph(payload: AnyIn, user=Depends(get_current_user)):
    return devqa.link_graph(payload.data().get("pages") or [])


# ---------------------------------------------------------------- security

@router.post("/devqa/security/scope/validate")
async def scope_validate(payload: AnyIn, user=Depends(get_current_user)):
    try:
        return devqa.validate_scope_file(payload.data().get("scope") or {})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/devqa/security/scope/check")
async def scope_check(payload: AnyIn, user=Depends(get_current_user)):
    d = payload.data()
    try:
        scope = devqa.validate_scope_file(d.get("scope") or {})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"target": d.get("target"), "allowed": devqa.scope_allows(d.get("target") or "", scope)}


@router.post("/devqa/security/findings/dedup")
async def findings_dedup(payload: AnyIn, user=Depends(get_current_user)):
    return {"findings": devqa.dedup_findings(payload.data().get("findings") or [])}


@router.post("/devqa/security/findings/cvss-guard")
async def findings_cvss_guard(payload: AnyIn, user=Depends(get_current_user)):
    errors = devqa.cvss_guard(payload.data().get("finding") or {})
    return {"valid": not errors, "errors": errors}


@router.post("/devqa/security/coverage")
async def security_coverage(payload: AnyIn, user=Depends(get_current_user)):
    d = payload.data()
    return devqa.coverage(int(d.get("discovered") or 0), int(d.get("probed") or 0))


@router.post("/devqa/security/gates")
async def security_gates(payload: AnyIn, user=Depends(get_current_user)):
    d = payload.data()
    return devqa.sandbox_gates(bool(d.get("docker_available")), bool(d.get("allow_fallback")))


@router.get("/devqa/security/checklist/{phase}")
async def security_checklist(phase: str, user=Depends(get_current_user)):
    try:
        return {"phase": phase, "checklist": devqa.security_checklist(phase)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/devqa/security/categories/reject")
async def security_categories(payload: AnyIn, user=Depends(get_current_user)):
    rejected = devqa.reject_excluded_categories(payload.data().get("categories") or [])
    return {"rejected": rejected,
            "import_allowed": not rejected,
            "note": "Any excluded category rejects the whole import."}


@router.post("/devqa/security/tools/availability")
async def security_tools(payload: AnyIn, user=Depends(get_current_user)):
    entries = payload.data().get("tools") or []
    return {"tools": devqa.tool_availability(entries, shutil.which),
            "note": "Missing tools are reported with install hints; Sangam never installs them."}


# ---------------------------------------------------------------- QA

@router.post("/devqa/qa/cassette-to-test")
async def qa_cassette_to_test(payload: AnyIn, user=Depends(get_current_user)):
    try:
        return devqa.cassette_to_pytest(payload.data().get("cassette") or {})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/devqa/qa/replay-diff")
async def qa_replay_diff(payload: AnyIn, user=Depends(get_current_user)):
    d = payload.data()
    return devqa.replay_diff(d.get("recorded") or {}, d.get("live") or {})


@router.post("/devqa/qa/js-lint")
async def qa_js_lint(payload: AnyIn, user=Depends(get_current_user)):
    d = payload.data()
    return {"findings": devqa.lint_js_source(d.get("source") or "", d.get("filename") or ""),
            "note": "Findings only — this endpoint never rewrites code."}


@router.post("/devqa/qa/suite-report")
async def qa_suite_report(payload: AnyIn, user=Depends(get_current_user)):
    return devqa.suite_report(payload.data().get("counts") or {})


@router.get("/devqa/qa/test-tags")
async def qa_test_tags(user=Depends(get_current_user)):
    return {"tags": devqa.TEST_TAGS}


# ---------------------------------------------------------------- platform

@router.get("/devqa/platform/health-actions")
async def platform_health_actions(user=Depends(get_current_user)):
    return {"actions": devqa.health_action_catalog(),
            "note": "Every action declares risk + reversibility. Actions without a declared "
                    "undo do not exist in this catalogue."}


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=500)


@router.post("/devqa/platform/services", status_code=201)
async def platform_add_service(payload: ServiceIn, user=Depends(get_current_user)):
    from urllib.parse import urlparse as _up

    if _up(payload.url).scheme not in ("http", "https"):
        raise HTTPException(status_code=422, detail="service url must be http(s)")
    conn = _conn()
    try:
        sid = devqa.new_id("svc")
        conn.execute("INSERT INTO devqa_services VALUES (?,?,?,?)",
                     (sid, payload.name, payload.url, _now()))
        conn.commit()
        return {"id": sid, "name": payload.name, "url": payload.url}
    finally:
        conn.close()


@router.get("/devqa/platform/services")
async def platform_list_services(user=Depends(get_current_user)):
    conn = _conn()
    try:
        rows = conn.execute("SELECT * FROM devqa_services ORDER BY created_at").fetchall()
        return {"services": [_svc_out(r) for r in rows]}
    finally:
        conn.close()


@router.post("/devqa/platform/services/{service_id}/check")
async def platform_check_service(service_id: str, user=Depends(get_current_user)):
    """Probe a registered service URL now (GET, 10s timeout) and record
    the result in the SQLite uptime history. A failed probe records
    'down' — it is never reported as up."""
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM devqa_services WHERE id=?", (service_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="service not found")
        code: int | None = None
        latency: float | None = None
        try:
            import time

            start = time.monotonic()
            # trust_env=False: a health probe of a local service must never
            # be routed through an egress proxy (and proxy env parsing
            # must not break the probe).
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False,
                                         trust_env=False) as client:
                resp = await client.get(row["url"], headers={"User-Agent": "Sangam-health/1.0"})
            latency = round((time.monotonic() - start) * 1000, 1)
            code = resp.status_code
        except Exception:
            code, latency = None, None
        status = devqa.service_status(code, latency)
        conn.execute("INSERT INTO devqa_health_checks (service_id, checked_at, status, latency_ms, http_code)"
                     " VALUES (?,?,?,?,?)", (service_id, _now(), status, latency, code))
        conn.commit()
        return {"service_id": service_id, "status": status, "http_code": code, "latency_ms": latency}
    finally:
        conn.close()


@router.get("/devqa/platform/services/{service_id}/uptime")
async def platform_uptime(service_id: str, user=Depends(get_current_user)):
    conn = _conn()
    try:
        rows = conn.execute("SELECT status FROM devqa_health_checks WHERE service_id=?",
                            (service_id,)).fetchall()
        return {"service_id": service_id,
                **devqa.uptime_summary([{"status": r["status"]} for r in rows])}
    finally:
        conn.close()


class WebhookIn(BaseModel):
    title: str
    body: str = ""
    source: str = "webhook"
    secret: str | None = None


@router.post("/devqa/platform/notifications/webhook", status_code=201)
async def platform_webhook(payload: WebhookIn, user=Depends(get_current_user)):
    """Gotify-shaped webhook-in: requires the SANGAM_DEVQA_WEBHOOK_SECRET
    env secret to be configured and matched. No external push service."""
    import os

    try:
        note = devqa.webhook_notification(payload.model_dump(), os.environ.get("SANGAM_DEVQA_WEBHOOK_SECRET"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conn = _conn()
    try:
        nid = devqa.new_id("ntf")
        conn.execute("INSERT INTO devqa_notifications VALUES (?,?,?,?,?,?)",
                     (nid, note["title"], note["body"], note["source"], 0, _now()))
        conn.commit()
        return {"id": nid, **note}
    finally:
        conn.close()


@router.get("/devqa/platform/notifications")
async def platform_notifications(user=Depends(get_current_user)):
    conn = _conn()
    try:
        rows = conn.execute("SELECT * FROM devqa_notifications ORDER BY created_at DESC").fetchall()
        return {"notifications": [{"id": r["id"], "title": r["title"], "body": r["body"],
                                   "source": r["source"], "read": bool(r["read"]),
                                   "created_at": r["created_at"]} for r in rows]}
    finally:
        conn.close()


@router.post("/devqa/platform/notifications/{note_id}/read")
async def platform_notification_read(note_id: str, user=Depends(get_current_user)):
    conn = _conn()
    try:
        cur = conn.execute("UPDATE devqa_notifications SET read=1 WHERE id=?", (note_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="notification not found")
        return {"id": note_id, "read": True}
    finally:
        conn.close()


@router.get("/devqa/platform/vm-profiles")
async def platform_vm_profiles(user=Depends(get_current_user)):
    return {"profiles": devqa.vm_profiles(),
            "note": "Documented external-tool configs only. Sangam never launches a VM."}


@router.get("/devqa/platform/winutil-catalog")
async def platform_winutil(user=Depends(get_current_user)):
    return {"entries": devqa.WINUTIL_CATALOG,
            "note": "Read-only checks + documented-only tweaks. Nothing here is executed by the server; "
                    "the user runs checks on their own Windows machine."}


@router.post("/devqa/platform/analytics/event")
async def platform_analytics_event(payload: AnyIn, user=Depends(get_current_user)):
    d = payload.data()
    errors = devqa.validate_event(d.get("name") or "", d.get("properties") or {})
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    return {"accepted": True, "name": d.get("name"),
            "note": "Taxonomy-validated. Aggregate stats remain on /analytics/stats."}


@router.post("/devqa/platform/analytics/funnel")
async def platform_analytics_funnel(payload: AnyIn, user=Depends(get_current_user)):
    d = payload.data()
    return {"funnel": devqa.funnel(d.get("events") or [], d.get("steps") or [])}


# ---------------------------------------------------------------- chat parity

@router.get("/devqa/chat/prompt-templates")
async def chat_prompt_templates(user=Depends(get_current_user)):
    return {"templates": devqa.PROMPT_TEMPLATES}


class FolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.post("/devqa/chat/folders", status_code=201)
async def chat_create_folder(payload: FolderIn, user=Depends(get_current_user)):
    conn = _conn()
    try:
        fid = devqa.new_id("fld")
        conn.execute("INSERT INTO devqa_folders VALUES (?,?,?)", (fid, payload.name, "[]"))
        conn.commit()
        return {"id": fid, "name": payload.name, "chat_ids": []}
    finally:
        conn.close()


@router.get("/devqa/chat/folders")
async def chat_list_folders(user=Depends(get_current_user)):
    conn = _conn()
    try:
        rows = conn.execute("SELECT * FROM devqa_folders").fetchall()
        return {"folders": [{"id": r["id"], "name": r["name"],
                             "chat_ids": json.loads(r["chat_ids"])} for r in rows]}
    finally:
        conn.close()


class FolderChatIn(BaseModel):
    chat_id: str


@router.post("/devqa/chat/folders/{folder_id}/chats")
async def chat_folder_add(folder_id: str, payload: FolderChatIn, user=Depends(get_current_user)):
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM devqa_folders WHERE id=?", (folder_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="folder not found")
        ids = json.loads(row["chat_ids"])
        if payload.chat_id not in ids:
            ids.append(payload.chat_id)
        conn.execute("UPDATE devqa_folders SET chat_ids=? WHERE id=?", (json.dumps(ids), folder_id))
        conn.commit()
        return {"id": folder_id, "name": row["name"], "chat_ids": ids}
    finally:
        conn.close()


@router.post("/devqa/chat/presets/share", status_code=201)
async def chat_preset_share(payload: AnyIn, user=Depends(get_current_user)):
    try:
        shared = devqa.share_preset(payload.data())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conn = _conn()
    try:
        pid = devqa.new_id("pre")
        conn.execute("INSERT INTO devqa_presets VALUES (?,?,?,?,?,?)",
                     (pid, shared["name"], shared["model"], shared["system"],
                      shared["temperature"], shared["share_code"]))
        conn.commit()
        return {"id": pid, **shared}
    finally:
        conn.close()


@router.get("/devqa/chat/presets")
async def chat_preset_list(user=Depends(get_current_user)):
    conn = _conn()
    try:
        rows = conn.execute("SELECT * FROM devqa_presets").fetchall()
        return {"presets": [{"id": r["id"], "name": r["name"], "model": r["model"],
                             "system": r["system"], "temperature": r["temperature"],
                             "share_code": r["share_code"]} for r in rows]}
    finally:
        conn.close()
