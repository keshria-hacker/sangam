"""
api_routes/memory_research_routes.py — Batch 9: Unified Memory +
Research (memory-research deep-read batch).

All routes mount on the shared router (importing this module
registers them AND the Observation / ResearchJob tables on
Base.metadata, following the Batch 4 precedent). Same auth + error
envelope as the rest of the API; single-user, no new destination.

  Observations (hindsight-inspired ledger):
    GET    /memory/observations            list (kind filter, closed opt-in)
    GET    /memory/observations/{id}
    POST   /memory/observations            mint (defense-scanned; block -> 422)
    POST   /memory/observations/{id}/refine  supports|contradicts|extends
    POST   /memory/observations/{id}/supersede
    GET    /memory/observations-context    chat-recall block (same text chat injects)
  Memory ops (mem0-style ADD/UPDATE/DELETE/NONE):
    POST   /memory/ops/preview             never writes
    POST   /memory/ops/apply               writes only with confirm=true
  Memory-as-Markdown notes (iwe contract):
    GET    /memory/notes
    GET    /memory/notes/{filename}
    POST   /memory/notes                   write dated typed note
    POST   /memory/notes/normalize         merge duplicates, report what merged
  Research jobs (gpt-researcher-inspired state machine):
    POST   /research/jobs                  create (planned)
    GET    /research/jobs/{id}
    POST   /research/jobs/{id}/run         execute; mirrored to Runs on done
    POST   /research/jobs/{id}/report      cited report; 422 on uncited claims
    GET    /research/jobs/{id}/source-graph  own-sources-only sketch
    POST   /research/jobs/{id}/slides      guarded slide/lesson outline
    POST   /notebooks/{nb_id}/deep-research notebook-scoped job
    GET    /notebooks/{nb_id}/timeline     source timeline (added order)
  Packs (repomix-style) + code memory + catalogue:
    POST   /knowledge/packs                workspace-gated pack
    POST   /knowledge/code-map/refresh     rebuild code graph only if stale
    POST   /knowledge/code-map/change-impact
    POST   /knowledge/code-map/analysis    hubs + cross-layer links
    GET    /knowledge/catalogue            curated MCP/pattern catalogue

Honest limits:
- The research planner is a deterministic template planner and the
  depth follow-ups are keyword-derived; no LLM is involved, and no
  route pretends otherwise. A model-backed planner is a future
  upgrade, not a hidden behaviour.
- Pack token counts are chars/4 estimates.
- Catalogue entries are a curated snapshot (2026-10-26), not a live
  index, and install routes are documentation — nothing here
  installs or executes a remote server.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..memory import defense
from ..memory.markdown_notes import (
    list_memory_notes,
    normalize_memory_notes,
    read_memory_note,
    write_memory_note,
)
from ..memory.observations import (
    list_observations,
    mint_observation,
    observation_context_block,
    observation_out,
    refine_observation,
    supersede_observation,
    Observation,
)
from ..memory.ops import apply_ops, preview_ops
from ..memory.store import list_memories
from ..models import AgentRun
from ..research import catalogue as catalogue_mod
from ..research import code_memory
from ..research import pack as pack_mod
from ..research.deep_research import (
    UncitedClaimError,
    ResearchJob,
    report_to_slides,
    research_job_out,
    run_job,
    source_graph,
    write_report,
)
from .common import router
from .notebooks_routes import Notebook, NotebookSource

__all__ = [
    "list_observation_rows", "get_observation", "create_observation",
    "refine_observation_endpoint", "supersede_observation_endpoint",
    "observation_context_endpoint", "preview_memory_ops", "apply_memory_ops",
    "list_note_rows", "get_note_row", "create_note_row", "normalize_note_rows",
    "create_research_job", "get_research_job", "run_research_job",
    "report_research_job", "research_source_graph", "research_slides",
    "notebook_deep_research", "notebook_timeline", "create_pack",
    "refresh_code_map", "code_change_impact", "code_map_analysis",
    "search_catalogue_endpoint",
]


def _uid(user) -> str:
    return str(user.id)


async def _get_job(db: AsyncSession, user_id: str, job_id: str) -> ResearchJob:
    job = await db.get(ResearchJob, job_id)
    if job is None or job.user_id != user_id:
        raise HTTPException(status_code=404, detail="Research job not found")
    return job


# ------------------------------------------------------------- observations

@router.get("/memory/observations")
async def list_observation_rows(kind: str | None = None,
                                include_closed: bool = False,
                                limit: int = 50,
                                db: AsyncSession = Depends(get_db),
                                user=Depends(get_current_user)):
    rows = await list_observations(db, _uid(user), kind=kind,
                                   include_closed=include_closed, limit=limit)
    return {"observations": [observation_out(r) for r in rows]}


# NOTE: the literal /memory/observations-context route MUST register
# before /memory/observations/{observation_id}, or FastAPI matches
# "observations-context" as an id and the context endpoint 404s.
@router.get("/memory/observations-context")
async def observation_context_endpoint(limit: int = 3,
                                       db: AsyncSession = Depends(get_db),
                                       user=Depends(get_current_user)):
    block, ids = await observation_context_block(db, _uid(user), limit=limit)
    return {"context_block": block, "observation_ids": ids}


@router.get("/memory/observations/{observation_id}")
async def get_observation(observation_id: str,
                          db: AsyncSession = Depends(get_db),
                          user=Depends(get_current_user)):
    row = await db.get(Observation, observation_id)
    if row is None or row.user_id != _uid(user):
        raise HTTPException(status_code=404, detail="Observation not found")
    return observation_out(row)


class ObservationIn(BaseModel):
    kind: str = "fact"
    claim: str
    evidence: list[dict] = Field(default_factory=list)
    expires_at: str | None = None


@router.post("/memory/observations", status_code=201)
async def create_observation(payload: ObservationIn,
                             db: AsyncSession = Depends(get_db),
                             user=Depends(get_current_user)):
    scan = defense.scan_text(payload.claim)
    if scan["action"] == "block":
        raise HTTPException(
            status_code=422,
            detail="Observation refused: claim looks like it contains a credential or private key.")
    claim = scan["redacted_text"]
    expires = None
    if payload.expires_at:
        try:
            expires = datetime.fromisoformat(payload.expires_at)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="expires_at must be ISO-8601") from exc
    try:
        row, created = await mint_observation(
            db, _uid(user), payload.kind, claim, payload.evidence, expires_at=expires)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    out = observation_out(row)
    out["created"] = created
    out["redacted"] = scan["action"] == "redact"
    return out


class RefineIn(BaseModel):
    evidence: list[dict] = Field(default_factory=list)
    verdict: str


@router.post("/memory/observations/{observation_id}/refine")
async def refine_observation_endpoint(observation_id: str, payload: RefineIn,
                                     db: AsyncSession = Depends(get_db),
                                     user=Depends(get_current_user)):
    try:
        row = await refine_observation(db, _uid(user), observation_id,
                                       payload.evidence, payload.verdict)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Observation not found")
    return observation_out(row)


class SupersedeIn(BaseModel):
    replacement_id: str | None = None


@router.post("/memory/observations/{observation_id}/supersede")
async def supersede_observation_endpoint(observation_id: str, payload: SupersedeIn,
                                        db: AsyncSession = Depends(get_db),
                                        user=Depends(get_current_user)):
    try:
        row = await supersede_observation(db, _uid(user), observation_id,
                                          payload.replacement_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Observation not found")
    return observation_out(row)


# --------------------------------------------------------------- memory ops

class OpsPreviewIn(BaseModel):
    content: str


@router.post("/memory/ops/preview")
async def preview_memory_ops(payload: OpsPreviewIn,
                             user=Depends(get_current_user)):
    existing = await list_memories(user_id="", limit=50)
    return {"decisions": preview_ops(payload.content, existing),
            "note": "Preview only — nothing was written."}


class OpsApplyIn(BaseModel):
    decisions: list[dict] = Field(default_factory=list)
    confirm: bool = False


@router.post("/memory/ops/apply")
async def apply_memory_ops(payload: OpsApplyIn,
                           user=Depends(get_current_user)):
    existing = await list_memories(user_id="", limit=50)
    known = {r.id for r in existing}
    try:
        result = await apply_ops(payload.decisions, known, confirm=payload.confirm)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result


# ------------------------------------------------------- markdown notes

@router.get("/memory/notes")
async def list_note_rows(user=Depends(get_current_user)):
    notes = list_memory_notes()
    if not notes:
        return {"notes": [], "empty_state": (
            "No memory notes yet. Notes appear here when memory is saved "
            "as dated, typed Markdown — one browsable folder you can read "
            "and correct by hand.")}
    return {"notes": notes}


@router.get("/memory/notes/{filename}")
async def get_note_row(filename: str, user=Depends(get_current_user)):
    note = read_memory_note(filename)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


class NoteIn(BaseModel):
    type: str = "note"
    title: str
    body: str = ""
    source: str = ""


@router.post("/memory/notes", status_code=201)
async def create_note_row(payload: NoteIn, user=Depends(get_current_user)):
    try:
        return write_memory_note(payload.type, payload.title, payload.body,
                                 source=payload.source)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/memory/notes/normalize")
async def normalize_note_rows(user=Depends(get_current_user)):
    return normalize_memory_notes()


# ------------------------------------------------------------ research jobs

class ResearchJobIn(BaseModel):
    question: str
    breadth: int = 4
    depth: int = 2
    word_budget: int = 2000
    notebook_id: str | None = None


@router.post("/research/jobs", status_code=201)
async def create_research_job(payload: ResearchJobIn,
                              db: AsyncSession = Depends(get_db),
                              user=Depends(get_current_user)):
    if not payload.question.strip():
        raise HTTPException(status_code=422, detail="question must not be empty")
    if payload.notebook_id:
        notebook = await db.get(Notebook, payload.notebook_id)
        if notebook is None or notebook.user_id != _uid(user):
            raise HTTPException(status_code=404, detail="Notebook not found")
    job = ResearchJob(
        id=f"rj-{uuid.uuid4().hex[:12]}", user_id=_uid(user),
        notebook_id=payload.notebook_id, question=payload.question.strip(),
        breadth=min(max(1, payload.breadth), 8),
        depth=min(max(1, payload.depth), 4),
        word_budget=min(max(100, payload.word_budget), 20000),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return research_job_out(job)


@router.get("/research/jobs/{job_id}")
async def get_research_job(job_id: str,
                           db: AsyncSession = Depends(get_db),
                           user=Depends(get_current_user)):
    return research_job_out(await _get_job(db, _uid(user), job_id))


async def _default_search(query: str) -> list[dict]:
    from ..websearch import web_search

    results = await web_search(query, max_results=5)
    return [{"title": r.title, "url": r.url, "snippet": r.snippet or ""}
            for r in results]


async def _default_fetch(url: str) -> str:
    from ..ingest_url import fetch_page_text

    _title, text = await fetch_page_text(url)
    return text


@router.post("/research/jobs/{job_id}/run")
async def run_research_job(job_id: str,
                           db: AsyncSession = Depends(get_db),
                           user=Depends(get_current_user)):
    job = await _get_job(db, _uid(user), job_id)
    if job.status == "done":
        return research_job_out(job)
    job = await run_job(db, job, search_fn=_default_search, fetch_fn=_default_fetch)
    if job.status == "done":
        # Paperclip governance: research jobs surface in the Runs centre.
        db.add(AgentRun(
            id=f"run-{uuid.uuid4().hex[:12]}", user_id=_uid(user),
            kind="research", title=f"Research: {job.question[:150]}",
            status="done", tokens=0, steps_json=json.dumps(
                [{"status": job.status, "sources": len(json.loads(job.sources_json or '[]'))}]),
            created_at=datetime.now(UTC),
        ))
        await db.commit()
    return research_job_out(job)


class ReportIn(BaseModel):
    claims: list[dict] = Field(default_factory=list)


@router.post("/research/jobs/{job_id}/report")
async def report_research_job(job_id: str, payload: ReportIn,
                              db: AsyncSession = Depends(get_db),
                              user=Depends(get_current_user)):
    job = await _get_job(db, _uid(user), job_id)
    learnings = json.loads(job.learnings_json or "[]")
    if not learnings:
        raise HTTPException(
            status_code=422,
            detail="Job has no learnings yet — run it before writing a report.")
    try:
        report = write_report(job.question, learnings, payload.claims)
    except UncitedClaimError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job.report_md = report
    job.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(job)
    return {"job_id": job.id, "report": report,
            "citations": json.loads(job.citations_json or "[]")}


@router.get("/research/jobs/{job_id}/source-graph")
async def research_source_graph(job_id: str,
                                db: AsyncSession = Depends(get_db),
                                user=Depends(get_current_user)):
    job = await _get_job(db, _uid(user), job_id)
    sources = json.loads(job.sources_json or "[]")
    return source_graph(sources)


@router.post("/research/jobs/{job_id}/slides")
async def research_slides(job_id: str,
                          db: AsyncSession = Depends(get_db),
                          user=Depends(get_current_user)):
    job = await _get_job(db, _uid(user), job_id)
    if not job.report_md:
        raise HTTPException(
            status_code=422,
            detail="Job has no report yet — write a cited report first.")
    return report_to_slides(job.report_md, json.loads(job.citations_json or "[]"))


@router.post("/notebooks/{notebook_id}/deep-research", status_code=201)
async def notebook_deep_research(notebook_id: str, payload: ResearchJobIn,
                                 db: AsyncSession = Depends(get_db),
                                 user=Depends(get_current_user)):
    notebook = await db.get(Notebook, notebook_id)
    if notebook is None or notebook.user_id != _uid(user):
        raise HTTPException(status_code=404, detail="Notebook not found")
    job = ResearchJob(
        id=f"rj-{uuid.uuid4().hex[:12]}", user_id=_uid(user),
        notebook_id=notebook_id, question=payload.question.strip(),
        breadth=min(max(1, payload.breadth), 8),
        depth=min(max(1, payload.depth), 4),
        word_budget=min(max(100, payload.word_budget), 20000),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return research_job_out(job)


@router.get("/notebooks/{notebook_id}/timeline")
async def notebook_timeline(notebook_id: str,
                            db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    notebook = await db.get(Notebook, notebook_id)
    if notebook is None or notebook.user_id != _uid(user):
        raise HTTPException(status_code=404, detail="Notebook not found")
    rows = (await db.execute(
        select(NotebookSource).where(NotebookSource.notebook_id == notebook_id)
        .order_by(NotebookSource.created_at)
    )).scalars().all()
    events = [{
        "event": "source_added", "source_id": row.id, "kind": row.kind,
        "ref": row.ref, "context_mode": row.context_mode,
        "ingest_status": row.ingest_status,
        "at": row.created_at.isoformat() if row.created_at else None,
    } for row in rows]
    return {"notebook_id": notebook_id, "events": events}


# ------------------------------------------------- packs / code map / catalogue

class PackIn(BaseModel):
    path: str = ""
    max_tokens: int = 8000


@router.post("/knowledge/packs")
async def create_pack(payload: PackIn, user=Depends(get_current_user)):
    from ..tools.builtin import _get_workspace_root, _is_path_allowed

    root = _get_workspace_root()
    target = Path(payload.path) if payload.path else root
    if not target.is_absolute():
        target = root / target
    try:
        resolved = target.resolve()
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"unresolvable path: {exc}") from exc
    if not _is_path_allowed(resolved):
        raise HTTPException(
            status_code=403,
            detail="Pack path must stay inside the workspace root.")
    try:
        return pack_mod.pack_directory(resolved, max_tokens=payload.max_tokens)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class CodeMapIn(BaseModel):
    path: str = ""


@router.post("/knowledge/code-map/refresh")
async def refresh_code_map(payload: CodeMapIn, user=Depends(get_current_user)):
    from ..tools.builtin import _get_workspace_root, _is_path_allowed

    root = _get_workspace_root()
    target = Path(payload.path) if payload.path else root
    if not target.is_absolute():
        target = root / target
    if not _is_path_allowed(target.resolve()):
        raise HTTPException(status_code=403, detail="Path must stay inside the workspace root.")
    return code_memory.refresh_if_stale(target)


class ChangeImpactIn(BaseModel):
    symbol: str
    path: str = ""


@router.post("/knowledge/code-map/change-impact")
async def code_change_impact(payload: ChangeImpactIn, user=Depends(get_current_user)):
    from .. import code_graph
    from ..tools.builtin import _get_workspace_root, _is_path_allowed

    root = _get_workspace_root()
    target = Path(payload.path) if payload.path else root
    if not target.is_absolute():
        target = root / target
    if not _is_path_allowed(target.resolve()):
        raise HTTPException(status_code=403, detail="Path must stay inside the workspace root.")
    graph, _warning = code_graph.ensure_fresh_graph(target)
    if graph is None:
        raise HTTPException(status_code=422, detail="Code graph could not be built.")
    return code_memory.change_impact(payload.symbol, graph)


@router.post("/knowledge/code-map/analysis")
async def code_map_analysis(payload: CodeMapIn, user=Depends(get_current_user)):
    from .. import code_graph
    from ..tools.builtin import _get_workspace_root, _is_path_allowed

    root = _get_workspace_root()
    target = Path(payload.path) if payload.path else root
    if not target.is_absolute():
        target = root / target
    if not _is_path_allowed(target.resolve()):
        raise HTTPException(status_code=403, detail="Path must stay inside the workspace root.")
    graph, _warning = code_graph.ensure_fresh_graph(target)
    if graph is None:
        raise HTTPException(status_code=422, detail="Code graph could not be built.")
    return {"hubs": code_memory.detect_hubs(graph),
            "surprising_links": code_memory.surprising_links(graph)}


@router.get("/knowledge/catalogue")
async def search_catalogue_endpoint(q: str = "", category: str = "",
                                    kind: str = "",
                                    user=Depends(get_current_user)):
    entries = catalogue_mod.search_catalogue(q=q, category=category, kind=kind)
    if not entries:
        return {"entries": [], "empty_state": (
            "No catalogue entries match. Try a broader search, or browse "
            "all MCP servers and LLM patterns with an empty query."),
            "catalogue_version": catalogue_mod.CATALOGUE_VERSION,
            "curated_on": catalogue_mod.CURATED_ON,
            "note": ("Curated snapshot — verify upstream before installing "
                     "anything. Nothing here installs itself.")}
    return {"entries": entries,
            "catalogue_version": catalogue_mod.CATALOGUE_VERSION,
            "curated_on": catalogue_mod.CURATED_ON,
            "note": ("Curated snapshot — verify upstream before installing "
                     "anything. Nothing here installs itself.")}
