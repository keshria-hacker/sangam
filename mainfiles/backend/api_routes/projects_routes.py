"""
api_routes/projects_routes.py — A3 (perfect-flow §3.1 Projects).

Persistent workspaces: a project holds instructions, files, sources,
a memory scope, a task list, and chats scoped to it. Destination-
agnostic by design: this module exposes the data + context API and
no top-level destination of its own — the coordinator's shell agent
mounts the companion frontend module under the new Projects
destination.

Reuse, not duplication
----------------------
* Tasks: the goals Task system (``goal_models.Task``) with
  ``project_id`` set — no second task table, no second lifecycle.
  ``task_out``/``set_task_status`` are shared with goals routes.
* Chats: the existing ``Chat`` row with ``project_id`` set.
* Retrieval: ``rag.retrieve_hybrid_chunks`` (vector + BM25 + RRF)
  plus the corrective grade/rewrite loop from knowledge_routes.
* URL ingest: notebooks' ingest-on-add (SSRF-guarded, deduped).

Scoping contract (proven by tests/test_a3_projects_memory.py)
------------------------------------------------------------
Project retrieval/context is built ONLY from that project's own
rows: its current instruction, its non-excluded sources (file refs
and ingested URL file_ids), its tasks, and its chats. The
``file_ids`` passed to hybrid retrieval are the project's own, so
retrieval in project A can never return project B's sources, and
the same prompt in two projects with different instructions
returns different assembled context.

Privacy
-------
No silent network calls: the only fetch in this module is URL
source ingest-on-add, which the user triggers by adding a URL
source (excluded sources skip the fetch entirely, exactly like
notebooks). No telemetry, no external calls from context/retrieve.

Tables live here (notebooks precedent): importing this module
registers them on Base.metadata. All tables carry created_at /
updated_at; Project and ProjectSource are soft-deleted
(``deleted_at``) — DELETE hides, ``?hard=true`` permanently
removes the project rows and unlinks (never deletes) its tasks
and chats, so user content is never destroyed by accident.

  POST   /projects
  GET    /projects
  GET    /projects/{id}
  PUT    /projects/{id}
  DELETE /projects/{id}             (soft; ?hard=true for permanent)
  POST   /projects/{id}/instructions
  GET    /projects/{id}/instructions
  POST   /projects/{id}/sources
  GET    /projects/{id}/sources
  PUT    /projects/{id}/sources/{source_id}/context
  DELETE /projects/{id}/sources/{source_id}   (soft)
  POST   /projects/{id}/tasks
  GET    /projects/{id}/tasks
  PATCH  /projects/{id}/tasks/{task_id}
  POST   /projects/{id}/chats
  GET    /projects/{id}/chats
  GET    /projects/{id}/context?q=
  GET    /projects/{id}/retrieve?q=
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, String, Text, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ..auth import get_current_user
from ..database import Base, get_db
from ..goal_models import Task, set_task_status, task_out
from ..models import Chat, Message, UploadedFile
from .common import router
from .knowledge_routes import grade_results, rewrite_query

__all__ = [
    "create_project", "list_projects", "get_project", "update_project",
    "delete_project", "add_project_instruction", "list_project_instructions",
    "add_project_source", "list_project_sources", "set_project_source_context",
    "delete_project_source", "create_project_task", "list_project_tasks",
    "update_project_task", "create_project_chat", "list_project_chats",
    "get_project_context", "retrieve_project",
]

CONTEXT_MODES = ("excluded", "summary", "full")
SOURCE_KINDS = ("file", "url", "chat")
MEMORY_SCOPES = ("project", "global")
MAX_CONTEXT_TEXT_CHARS = 12000


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ------------------------------------------------------------------ models

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    # "project" (default): context/retrieve use only this project's
    # sources. "global": retrieve also searches all uploaded files.
    memory_scope: Mapped[str] = mapped_column(String(16), default="project")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ProjectSource(Base):
    __tablename__ = "project_sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(32), ForeignKey("projects.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # file | url | chat
    ref: Mapped[str] = mapped_column(String(512))
    context_mode: Mapped[str] = mapped_column(String(16), default="full")
    summary_text: Mapped[str] = mapped_column(Text, default="")
    file_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    ingest_status: Mapped[str] = mapped_column(String(16), default="pending")
    ingest_error: Mapped[str] = mapped_column(Text, default="")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ProjectInstruction(Base):
    __tablename__ = "project_instructions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(32), ForeignKey("projects.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    is_current: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# -------------------------------------------------------------- serializers

def _project_out(row: Project) -> dict:
    return {"id": row.id, "name": row.name, "description": row.description,
            "memory_scope": row.memory_scope or "project",
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


def _source_out(row: ProjectSource) -> dict:
    return {"id": row.id, "project_id": row.project_id, "kind": row.kind,
            "ref": row.ref, "context_mode": row.context_mode,
            "summary_text": row.summary_text,
            "file_id": row.file_id,
            "ingest_status": row.ingest_status or "pending",
            "ingest_error": row.ingest_error or "",
            "created_at": row.created_at.isoformat() if row.created_at else None}


def _instruction_out(row: ProjectInstruction) -> dict:
    return {"id": row.id, "project_id": row.project_id,
            "content": row.content, "is_current": bool(row.is_current),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


def _chat_out(row: Chat) -> dict:
    return {"id": row.id, "title": row.title, "model": row.model,
            "project_id": row.project_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


async def _get_project(db: AsyncSession, user_id: str, project_id: str,
                       include_deleted: bool = False) -> Project:
    row = await db.get(Project, project_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    if row.deleted_at is not None and not include_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


async def _get_source(db: AsyncSession, user_id: str, project_id: str,
                      source_id: str) -> ProjectSource:
    row = await db.get(ProjectSource, source_id)
    if (row is None or row.user_id != user_id or row.project_id != project_id
            or row.deleted_at is not None):
        raise HTTPException(status_code=404, detail="Project source not found")
    return row


async def _current_instruction(db: AsyncSession, user_id: str,
                               project_id: str) -> ProjectInstruction | None:
    rows = (await db.execute(
        select(ProjectInstruction).where(
            ProjectInstruction.user_id == user_id,
            ProjectInstruction.project_id == project_id,
            ProjectInstruction.is_current.is_(True))
        .order_by(desc(ProjectInstruction.created_at), desc(ProjectInstruction.id))
        .limit(1)
    )).scalars().all()
    return rows[0] if rows else None


async def _live_sources(db: AsyncSession, user_id: str,
                        project_id: str) -> list[ProjectSource]:
    rows = (await db.execute(
        select(ProjectSource).where(
            ProjectSource.user_id == user_id,
            ProjectSource.project_id == project_id,
            ProjectSource.deleted_at.is_(None))
        .order_by(ProjectSource.created_at, ProjectSource.id)
    )).scalars().all()
    return list(rows)


async def _project_file_ids(db: AsyncSession, user_id: str,
                            project: Project) -> list[str]:
    """File ids retrieval may search — strictly this project's own
    file/url sources (non-excluded), or all uploads when the
    project's memory_scope is "global"."""
    if project.memory_scope == "global":
        rows = (await db.execute(select(UploadedFile).limit(200))).scalars().all()
        return [f.id for f in rows]
    ids: list[str] = []
    for source in await _live_sources(db, user_id, project.id):
        if source.context_mode == "excluded":
            continue
        if source.kind == "file":
            ids.append(source.ref)
        elif source.kind == "url" and source.file_id:
            ids.append(source.file_id)
    return ids


async def _source_text(db: AsyncSession, source: ProjectSource) -> tuple[str | None, str | None]:
    """Stored text for a source (no retrieval, no network)."""
    if source.kind == "file":
        row = await db.get(UploadedFile, source.ref)
        if row and row.extracted_text:
            return row.extracted_text, None
        return None, "No retrievable text for this file source."
    if source.kind == "chat":
        chat = await db.get(Chat, source.ref)
        if chat is None:
            return None, "Chat not found; its messages are unavailable."
        rows = (await db.execute(
            select(Message).where(Message.chat_id == chat.id)
            .order_by(Message.created_at, Message.id)
        )).scalars().all()
        if not rows:
            return None, "Chat has no messages."
        return "\n".join(f"{m.role}: {m.content}" for m in rows), None
    if source.file_id:
        row = await db.get(UploadedFile, source.file_id)
        if row and row.extracted_text:
            return row.extracted_text, None
        return None, "URL source was ingested but its document is unavailable."
    if source.ingest_status == "failed":
        return None, ("URL ingest failed"
                      + (f": {source.ingest_error}" if source.ingest_error else "")
                      + "; re-add the source to retry.")
    return None, ("URL source has no stored text yet; it was added "
                  "without ingestion (excluded sources skip ingest).")


def _truncate(text: str) -> tuple[str, str | None]:
    if len(text) <= MAX_CONTEXT_TEXT_CHARS:
        return text, None
    return (text[:MAX_CONTEXT_TEXT_CHARS]
            + f"\n[truncated to {MAX_CONTEXT_TEXT_CHARS} chars]"), "truncated"


# ---------------------------------------------------------------- projects

class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    memory_scope: Literal["project", "global"] = "project"


class ProjectUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    memory_scope: Literal["project", "global"] | None = None


@router.post("/projects", status_code=201)
async def create_project(
    payload: ProjectIn, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    row = Project(id=_new_id("prj"), user_id=user.id, name=payload.name,
                  description=payload.description or "",
                  memory_scope=payload.memory_scope)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _project_out(row)


@router.get("/projects")
async def list_projects(
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    rows = (await db.execute(
        select(Project).where(Project.user_id == user.id,
                              Project.deleted_at.is_(None))
        .order_by(desc(Project.updated_at), desc(Project.id))
    )).scalars().all()
    return {"projects": [_project_out(r) for r in rows]}


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    project = await _get_project(db, user.id, project_id)
    instruction = await _current_instruction(db, user.id, project.id)
    sources = await _live_sources(db, user.id, project.id)
    tasks = (await db.execute(
        select(Task).where(Task.user_id == user.id,
                           Task.project_id == project.id)
        .order_by(Task.created_at, Task.id)
    )).scalars().all()
    chats = (await db.execute(
        select(Chat).where(Chat.project_id == project.id)
        .order_by(desc(Chat.updated_at), desc(Chat.id))
    )).scalars().all()
    out = _project_out(project)
    out["instruction"] = instruction.content if instruction else ""
    out["source_count"] = len(sources)
    out["task_count"] = len(tasks)
    out["open_task_count"] = sum(1 for t in tasks if t.status not in ("done", "cancelled"))
    out["chat_count"] = len(chats)
    return out


@router.put("/projects/{project_id}")
async def update_project(
    project_id: str, payload: ProjectUpdateIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    row = await _get_project(db, user.id, project_id)
    if payload.name is not None:
        row.name = payload.name
    if payload.description is not None:
        row.description = payload.description
    if payload.memory_scope is not None:
        row.memory_scope = payload.memory_scope
    row.updated_at = _now()
    await db.commit()
    await db.refresh(row)
    return _project_out(row)


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str, hard: bool = Query(default=False),
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    row = await _get_project(db, user.id, project_id, include_deleted=True)
    if row.deleted_at is not None and not hard:
        raise HTTPException(status_code=404, detail="Project not found")
    if hard:
        for table in (ProjectSource, ProjectInstruction):
            children = (await db.execute(
                select(table).where(table.project_id == row.id)
            )).scalars().all()
            for child in children:
                await db.delete(child)
        # Unlink, never delete, the user's tasks and chats.
        for task in (await db.execute(
                select(Task).where(Task.project_id == row.id))).scalars().all():
            task.project_id = None
        for chat in (await db.execute(
                select(Chat).where(Chat.project_id == row.id))).scalars().all():
            chat.project_id = None
        await db.delete(row)
        await db.commit()
        return {"deleted": project_id, "hard": True}
    row.deleted_at = _now()
    row.updated_at = _now()
    await db.commit()
    return {"deleted": project_id, "hard": False}


# ------------------------------------------------------------- instructions

class InstructionIn(BaseModel):
    content: str = Field(min_length=1, max_length=20000)


@router.post("/projects/{project_id}/instructions", status_code=201)
async def add_project_instruction(
    project_id: str, payload: InstructionIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    project = await _get_project(db, user.id, project_id)
    previous = (await db.execute(
        select(ProjectInstruction).where(
            ProjectInstruction.user_id == user.id,
            ProjectInstruction.project_id == project.id,
            ProjectInstruction.is_current.is_(True))
    )).scalars().all()
    for old in previous:
        old.is_current = False
        old.updated_at = _now()
    row = ProjectInstruction(id=_new_id("pri"), project_id=project.id,
                             user_id=user.id, content=payload.content,
                             is_current=True)
    db.add(row)
    project.updated_at = _now()
    await db.commit()
    await db.refresh(row)
    return _instruction_out(row)


@router.get("/projects/{project_id}/instructions")
async def list_project_instructions(
    project_id: str, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    project = await _get_project(db, user.id, project_id)
    rows = (await db.execute(
        select(ProjectInstruction).where(
            ProjectInstruction.user_id == user.id,
            ProjectInstruction.project_id == project.id)
        .order_by(desc(ProjectInstruction.created_at), desc(ProjectInstruction.id))
    )).scalars().all()
    current = next((r for r in rows if r.is_current), None)
    return {"current": _instruction_out(current) if current else None,
            "history": [_instruction_out(r) for r in rows]}


# ------------------------------------------------------------------ sources

class ProjectSourceIn(BaseModel):
    kind: Literal["file", "url", "chat"]
    ref: str = Field(min_length=1, max_length=512)
    context_mode: Literal["excluded", "summary", "full"] = "full"
    summary_text: str = ""


@router.post("/projects/{project_id}/sources", status_code=201)
async def add_project_source(
    project_id: str, payload: ProjectSourceIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    from ..ingest_url import normalize_url
    from .notebooks_routes import _ingest_url_for_source

    project = await _get_project(db, user.id, project_id)
    if payload.kind == "file" and await db.get(UploadedFile, payload.ref) is None:
        raise HTTPException(status_code=404, detail="Knowledge file not found")
    if payload.kind == "chat" and await db.get(Chat, payload.ref) is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    existing = await _live_sources(db, user.id, project.id)
    if payload.kind == "url":
        if not (payload.ref.startswith("http://") or payload.ref.startswith("https://")):
            raise HTTPException(status_code=422, detail="URL sources need an http(s) URL as ref")
        target = normalize_url(payload.ref)
        for row in existing:
            if row.kind == "url" and normalize_url(row.ref) == target:
                return _source_out(row)
    else:
        for row in existing:
            if row.kind == payload.kind and row.ref == payload.ref:
                return _source_out(row)
    row = ProjectSource(
        id=_new_id("prs"), project_id=project.id, user_id=user.id,
        kind=payload.kind, ref=payload.ref, context_mode=payload.context_mode,
        summary_text=payload.summary_text or "")
    db.add(row)
    await db.flush()
    if payload.kind == "url" and payload.context_mode != "excluded":
        file_id, status, error = await _ingest_url_for_source(db, user.id, payload.ref)
        row.file_id = file_id
        row.ingest_status = status
        row.ingest_error = error
    else:
        row.ingest_status = "skipped" if payload.kind == "url" else "n/a"
    project.updated_at = _now()
    await db.commit()
    await db.refresh(row)
    return _source_out(row)


@router.get("/projects/{project_id}/sources")
async def list_project_sources(
    project_id: str, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    project = await _get_project(db, user.id, project_id)
    rows = await _live_sources(db, user.id, project.id)
    return {"sources": [_source_out(r) for r in rows]}


class ProjectSourceContextIn(BaseModel):
    context_mode: Literal["excluded", "summary", "full"]


@router.put("/projects/{project_id}/sources/{source_id}/context")
async def set_project_source_context(
    project_id: str, source_id: str, payload: ProjectSourceContextIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    from .notebooks_routes import _ingest_url_for_source

    project = await _get_project(db, user.id, project_id)
    row = await _get_source(db, user.id, project.id, source_id)
    row.context_mode = payload.context_mode
    # Same un-exclude fix as notebooks: a URL source added while
    # excluded skipped ingest, so restore it on un-exclude.
    if (row.kind == "url" and payload.context_mode != "excluded"
            and row.file_id is None
            and row.ingest_status in ("skipped", "failed")):
        file_id, status, error = await _ingest_url_for_source(db, user.id, row.ref)
        row.file_id = file_id
        row.ingest_status = status
        row.ingest_error = error
    await db.commit()
    await db.refresh(row)
    return _source_out(row)


@router.delete("/projects/{project_id}/sources/{source_id}")
async def delete_project_source(
    project_id: str, source_id: str,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    await _get_project(db, user.id, project_id)
    row = await _get_source(db, user.id, project_id, source_id)
    row.deleted_at = _now()
    await db.commit()
    return {"deleted": source_id}


# -------------------------------------------------------------------- tasks
# REUSED goals task system: Task rows with project_id set, goal_id NULL.

class ProjectTaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    parent_id: str | None = None
    priority: str = "medium"


class ProjectTaskUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: str | None = None
    priority: str | None = None


@router.post("/projects/{project_id}/tasks", status_code=201)
async def create_project_task(
    project_id: str, payload: ProjectTaskIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    project = await _get_project(db, user.id, project_id)
    parent = None
    if payload.parent_id is not None:
        parent = await db.get(Task, payload.parent_id)
        if parent is None or parent.user_id != user.id or parent.project_id != project.id:
            raise HTTPException(status_code=422, detail="Subtask parent belongs to another project")
    row = Task(id=_new_id("task"), user_id=user.id, goal_id=None,
               project_id=project.id, parent_id=payload.parent_id,
               title=payload.title, description=payload.description or "",
               priority=payload.priority)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return task_out(row)


@router.get("/projects/{project_id}/tasks")
async def list_project_tasks(
    project_id: str, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    project = await _get_project(db, user.id, project_id)
    rows = (await db.execute(
        select(Task).where(Task.user_id == user.id,
                           Task.project_id == project.id)
        .order_by(Task.created_at, Task.id)
    )).scalars().all()
    return {"project_id": project.id, "tasks": [task_out(r) for r in rows]}


@router.patch("/projects/{project_id}/tasks/{task_id}")
async def update_project_task(
    project_id: str, task_id: str, payload: ProjectTaskUpdateIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    project = await _get_project(db, user.id, project_id)
    row = await db.get(Task, task_id)
    if row is None or row.user_id != user.id or row.project_id != project.id:
        raise HTTPException(status_code=404, detail="Project task not found")
    if payload.title is not None:
        row.title = payload.title
    if payload.description is not None:
        row.description = payload.description
    if payload.priority is not None:
        row.priority = payload.priority
    if payload.status is not None:
        try:
            set_task_status(row, payload.status)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    row.updated_at = _now()
    await db.commit()
    await db.refresh(row)
    return task_out(row)


# -------------------------------------------------------------------- chats

class ProjectChatIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    model: str = ""


@router.post("/projects/{project_id}/chats", status_code=201)
async def create_project_chat(
    project_id: str, payload: ProjectChatIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    project = await _get_project(db, user.id, project_id)
    row = Chat(title=payload.title, model=payload.model or "",
               project_id=project.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _chat_out(row)


@router.get("/projects/{project_id}/chats")
async def list_project_chats(
    project_id: str, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    project = await _get_project(db, user.id, project_id)
    rows = (await db.execute(
        select(Chat).where(Chat.project_id == project.id)
        .order_by(desc(Chat.updated_at), desc(Chat.id))
    )).scalars().all()
    return {"project_id": project.id, "chats": [_chat_out(r) for r in rows]}


# ------------------------------------------------------- context + retrieve

@router.get("/projects/{project_id}/context")
async def get_project_context(
    project_id: str, q: str = Query(default=""),
    top_k: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    """Assembled project context for one prompt — the scoping proof
    surface. Instruction first, then (when q is given) hybrid
    retrieval over ONLY this project's file ids, then open tasks
    and project chats. Without q, source texts come from storage
    (summary mode honoured), truncated with a notice."""
    from ..rag import retrieve_hybrid_chunks

    project = await _get_project(db, user.id, project_id)
    instruction = await _current_instruction(db, user.id, project.id)
    sources = await _live_sources(db, user.id, project.id)
    tasks = (await db.execute(
        select(Task).where(Task.user_id == user.id,
                           Task.project_id == project.id,
                           Task.status.notin_(("done", "cancelled")))
        .order_by(Task.created_at, Task.id)
    )).scalars().all()
    chats = (await db.execute(
        select(Chat).where(Chat.project_id == project.id)
        .order_by(desc(Chat.updated_at), desc(Chat.id)).limit(20)
    )).scalars().all()
    entries: list[dict] = []
    retrieval: list[dict] = []
    if q:
        ids = await _project_file_ids(db, user.id, project)
        if ids:
            retrieval = retrieve_hybrid_chunks(q, ids, top_k=top_k)
            for r in retrieval:
                citation = r.get("citation") or {}
                citation.setdefault("provenance", "verified")
                r["citation"] = citation
    else:
        for source in sources:
            if source.context_mode == "excluded":
                continue
            if source.context_mode == "summary" and source.summary_text:
                entries.append({"source_id": source.id, "kind": source.kind,
                                "ref": source.ref, "mode": "summary",
                                "text": source.summary_text})
                continue
            text, note = await _source_text(db, source)
            if text is not None:
                fitted, trunc_note = _truncate(text)
                entry = {"source_id": source.id, "kind": source.kind,
                         "ref": source.ref, "mode": source.context_mode,
                         "text": fitted}
                if trunc_note:
                    entry["note"] = trunc_note
                entries.append(entry)
            else:
                entries.append({"source_id": source.id, "kind": source.kind,
                                "ref": source.ref, "mode": source.context_mode,
                                "note": note})
    return {
        "project_id": project.id,
        "memory_scope": project.memory_scope or "project",
        "instruction": instruction.content if instruction else "",
        "retrieval": retrieval,
        "sources": entries,
        "open_tasks": [task_out(t) for t in tasks],
        "chats": [_chat_out(c) for c in chats],
    }


@router.get("/projects/{project_id}/retrieve")
async def retrieve_project(
    project_id: str, q: str = Query(min_length=1),
    top_k: int = Query(default=5, ge=1, le=20),
    grade_threshold: float = Query(default=0.35, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    """Project-scoped hybrid retrieval with the corrective loop
    (grade → query-rewrite retry) from /knowledge/retrieve. Every
    citation carries its grade and provenance ("verified" for
    stored chunks). Deliberately NO graph expansion and NO web
    fallback here: both would surface out-of-project evidence and
    break the scoping contract."""
    from ..rag import retrieve_hybrid_chunks

    project = await _get_project(db, user.id, project_id)
    ids = await _project_file_ids(db, user.id, project)
    results = retrieve_hybrid_chunks(q, ids, top_k=top_k) if ids else []
    grade, top_score = grade_results(results, threshold=grade_threshold)
    fallback_used = "none"
    used_query = q
    if grade == "weak" and ids:
        rewritten = rewrite_query(q)
        if rewritten != q:
            retried = retrieve_hybrid_chunks(rewritten, ids, top_k=top_k)
            if retried:
                results = retried
                used_query = rewritten
                fallback_used = "query-rewrite"
                grade, top_score = grade_results(results, threshold=grade_threshold)
    for r in results:
        citation = r.get("citation") or {}
        citation["grade"] = grade
        citation.setdefault("provenance", "verified")
        r["citation"] = citation
    return {"project_id": project.id, "query": q, "used_query": used_query,
            "method": "hybrid", "grade": grade,
            "top_score": round(top_score, 4), "fallback_used": fallback_used,
            "memory_scope": project.memory_scope or "project",
            "results": results}
