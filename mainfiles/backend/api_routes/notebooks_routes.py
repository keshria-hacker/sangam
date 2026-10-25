"""
api_routes/notebooks_routes.py — Batch 4: Research Notebooks
(open-notebook-style grouping, Sangam-native).

Tables live here (not models.py), following the Batch 2 precedent:
importing this module registers them on Base.metadata.

  POST   /notebooks
  GET    /notebooks
  GET    /notebooks/{id}
  PUT    /notebooks/{id}
  DELETE /notebooks/{id}
  POST   /notebooks/{id}/sources
  GET    /notebooks/{id}/sources
  PUT    /notebooks/{id}/sources/{source_id}/context
  GET    /notebooks/{id}/retrieve?q=
  POST   /notebooks/{id}/notes
  GET    /notebooks/{id}/notes
  GET    /notebooks/{id}/notes/{note_id}          (includes outgoing [[links]])
  POST   /notebooks/{id}/notes/from-chat
  GET    /notebooks/{id}/notes/{note_id}/backlinks
  POST   /notebooks/{id}/transforms               (stores transform AND a note)
  GET    /notebooks/{id}/transforms

Honest limits:
- Retrieve honours context modes: excluded sources are skipped, summary
  sources use stored summary_text or an extractive first-500-chars
  fallback (labelled as such), full sources use full stored text.
- File sources in retrieve use RAG chunks for the query when indexed,
  falling back to the file's stored extracted text; a source with no
  retrievable text is listed by ref with a note — never invented text.
- URL sources are ingested on add (SSRF-guarded, best-effort): the
  fetched text is stored as a document and joined to the source row
  via ``file_id``, so retrieve returns the page's own text. A failed
  fetch never blocks creating the source — the row records
  ``ingest_status="failed"`` and retrieve lists the note instead.
  Excluded sources skip the fetch entirely (nothing to retrieve).
  Re-adding the same normalized URL to a notebook returns the
  existing source row; re-ingesting across notebooks reuses the
  stored document instead of fetching again.
- Context assembly is token-budgeted (default 8000 tokens, ~chars/4
  estimate): texts truncate with an explicit notice, and sources past
  the budget are listed as omitted — never silently dropped.
- Transforms need a configured model (503 otherwise, never fake text).
"""
from __future__ import annotations

import json
import re
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
from ..ingest_url import fetch_page_text, normalize_url
from ..memory import extract_llm
from ..models import Chat, Message, UploadedFile
from ..note_graph import (
    NoteLinkIndex,
    expand_retrieval,
    extract_section,
    index_note_rows,
    rename_note_propagate,
)
from .common import router

__all__ = [
    "create_notebook", "list_notebooks", "get_notebook", "update_notebook",
    "delete_notebook", "add_notebook_source", "list_notebook_sources",
    "set_source_context", "retrieve_notebook", "create_notebook_note",
    "list_notebook_notes", "get_notebook_note", "note_from_chat",
    "run_notebook_transform", "list_notebook_transforms", "get_note_backlinks",
    "create_saved_transform", "list_saved_transforms",
    "list_notebook_insights", "save_insight_as_note",
    "update_notebook_note", "extract_note_section", "expand_note_graph",
]


async def _rebuild_note_index(db: AsyncSession, notebook_id: str) -> None:
    """Rebuild the notebook's link index from current note contents.

    Whole-notebook rebuild (not per-note): a new note titled X also
    resolves previously-dangling [[X]] links in older notes, so the
    index must be recomputed for every note, not just the edited one.
    Best-effort: index failure never blocks the note write itself.
    """
    try:
        rows = (await db.execute(
            select(NotebookNote).where(NotebookNote.notebook_id == notebook_id)
        )).scalars().all()
        notes_by_title = {r.title: r.id for r in rows}
        await db.execute(
            NoteLinkIndex.__table__.delete().where(
                NoteLinkIndex.notebook_id == notebook_id))
        for r in rows:
            for link_row in index_note_rows(
                    {"id": r.id, "notebook_id": notebook_id,
                     "content": r.content or ""}, notes_by_title):
                db.add(NoteLinkIndex(**link_row))
        await db.commit()
    except Exception:  # noqa: BLE001 — index is derived data, never fatal
        await db.rollback()

CONTEXT_MODES = ("excluded", "summary", "full")
SOURCE_KINDS = ("file", "url", "note", "chat")
WIKI_RE = re.compile(r"\[\[([^\]]+)\]\]")
DEFAULT_CONTEXT_BUDGET_TOKENS = 8000


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ------------------------------------------------------------------ models

class Notebook(Base):
    __tablename__ = "notebooks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class NotebookSource(Base):
    __tablename__ = "notebook_sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    notebook_id: Mapped[str] = mapped_column(String(32), ForeignKey("notebooks.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # file | url | note | chat
    ref: Mapped[str] = mapped_column(String(512))
    context_mode: Mapped[str] = mapped_column(String(16), default="full")
    summary_text: Mapped[str] = mapped_column(Text, default="")
    # Wave-2: ingest-on-add join. URL sources store the ingested
    # document's file_id here; ingest_status tracks the fetch.
    file_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    ingest_status: Mapped[str] = mapped_column(String(16), default="pending")
    ingest_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class NotebookNote(Base):
    __tablename__ = "notebook_notes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    notebook_id: Mapped[str] = mapped_column(String(32), ForeignKey("notebooks.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    source_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    source_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class NotebookTransform(Base):
    __tablename__ = "notebook_transforms"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    notebook_id: Mapped[str] = mapped_column(String(32), ForeignKey("notebooks.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text, default="")
    output: Mapped[str] = mapped_column(Text, default="")
    source_ids: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class NotebookSavedTransform(Base):
    """A reusable named prompt (open-notebook Transformation). With
    ``apply_default`` set, it runs automatically over each new source
    added to the notebook (best-effort: skipped when no model is
    configured, never a blocking failure)."""
    __tablename__ = "notebook_saved_transforms"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    notebook_id: Mapped[str] = mapped_column(String(32), ForeignKey("notebooks.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text, default="")
    apply_default: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class NotebookInsight(Base):
    """A first-class insight row: model output about one source
    (or about a transform run when source_id is NULL). Insights are
    distinct from notes; ``save-as-note`` promotes one into a note
    with provenance instead of conflating the two."""
    __tablename__ = "notebook_insights"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    notebook_id: Mapped[str] = mapped_column(String(32), ForeignKey("notebooks.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    transform_name: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# -------------------------------------------------------------- serializers

def _nb_out(row: Notebook) -> dict:
    return {"id": row.id, "name": row.name, "description": row.description,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


def _source_out(row: NotebookSource) -> dict:
    return {"id": row.id, "notebook_id": row.notebook_id, "kind": row.kind,
            "ref": row.ref, "context_mode": row.context_mode,
            "summary_text": row.summary_text,
            "file_id": row.file_id,
            "ingest_status": row.ingest_status or "pending",
            "ingest_error": row.ingest_error or "",
            "created_at": row.created_at.isoformat() if row.created_at else None}


def _saved_transform_out(row: NotebookSavedTransform) -> dict:
    return {"id": row.id, "notebook_id": row.notebook_id, "name": row.name,
            "prompt": row.prompt, "apply_default": bool(row.apply_default),
            "created_at": row.created_at.isoformat() if row.created_at else None}


def _insight_out(row: NotebookInsight) -> dict:
    return {"id": row.id, "notebook_id": row.notebook_id,
            "source_id": row.source_id, "transform_name": row.transform_name,
            "content": row.content,
            "created_at": row.created_at.isoformat() if row.created_at else None}


def parse_wiki_links(content: str) -> list[str]:
    """Titles referenced as [[Title]] in note content, order-preserved."""
    found: list[str] = []
    for match in WIKI_RE.finditer(content or ""):
        title = match.group(1).strip()
        if title and title not in found:
            found.append(title)
    return found


def _note_out(row: NotebookNote, with_links: bool = False) -> dict:
    out = {"id": row.id, "notebook_id": row.notebook_id, "title": row.title,
           "content": row.content, "source_chat_id": row.source_chat_id,
           "source_message_id": row.source_message_id,
           "created_at": row.created_at.isoformat() if row.created_at else None}
    if with_links:
        out["outgoing_links"] = parse_wiki_links(row.content)
    return out


def _transform_out(row: NotebookTransform) -> dict:
    try:
        source_ids = json.loads(row.source_ids or "[]")
    except ValueError:
        source_ids = []
    return {"id": row.id, "notebook_id": row.notebook_id, "name": row.name,
            "prompt": row.prompt, "output": row.output, "source_ids": source_ids,
            "created_at": row.created_at.isoformat() if row.created_at else None}


async def _get_notebook(db: AsyncSession, user_id: str, nb_id: str) -> Notebook:
    row = await db.get(Notebook, nb_id)
    if not row or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Notebook not found")
    return row


async def _get_source(db: AsyncSession, user_id: str, nb_id: str, source_id: str) -> NotebookSource:
    row = await db.get(NotebookSource, source_id)
    if not row or row.user_id != user_id or row.notebook_id != nb_id:
        raise HTTPException(status_code=404, detail="Notebook source not found")
    return row


async def _get_note(db: AsyncSession, user_id: str, nb_id: str, note_id: str) -> NotebookNote:
    row = await db.get(NotebookNote, note_id)
    if not row or row.user_id != user_id or row.notebook_id != nb_id:
        raise HTTPException(status_code=404, detail="Notebook note not found")
    return row


# ------------------------------------------------------------ source texts

async def _full_source_text(
    db: AsyncSession, source: NotebookSource, q: str
) -> tuple[str | None, str | None]:
    """(full text, note). Text None means 'no retrievable text' — the
    caller lists the ref with the note instead of inventing content."""
    if source.kind == "file":
        if q:
            try:
                from ..rag import retrieve_relevant_chunks
                chunks = retrieve_relevant_chunks(q, [source.ref], top_k=10)
                texts = [c.get("text", "") for c in chunks if c.get("text")]
                if texts:
                    return "\n\n".join(texts), None
            except Exception:  # noqa: BLE001 — fall back to stored text
                pass
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
    if source.kind == "note":
        row = await db.get(NotebookNote, source.ref)
        if row is None:
            return None, "Note not found."
        return row.content or "", None
    # kind == "url": ingested documents are joined via file_id
    # (ingest-on-add). An un-ingested source keeps the old note.
    if source.file_id:
        if q:
            try:
                from ..rag import retrieve_relevant_chunks
                chunks = retrieve_relevant_chunks(q, [source.file_id], top_k=10)
                texts = [c.get("text", "") for c in chunks if c.get("text")]
                if texts:
                    return "\n\n".join(texts), None
            except Exception:  # noqa: BLE001 — fall back to stored text
                pass
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


def _estimate_tokens(text: str) -> int:
    """~chars/4 token estimate (same approximation rag chunking
    uses). Deliberately dependency-free: the notebook path must not
    require a model-specific tiktoken encoding to stay budgeted."""
    return max(1, len(text) // 4)


async def _ingest_url_for_source(
    db: AsyncSession, user_id: str, url: str,
) -> tuple[str | None, str, str]:
    """Ingest-on-add for a notebook URL source. Returns
    (file_id, status, error). Dedupe first: a document already
    ingested for this normalized URL (any notebook of this user) is
    reused without refetching. Fetch failures return status
    "failed" with the error — they never raise into add-source."""
    from ..ingest_url import slug_from_url
    from ..rag import index_document

    target = normalize_url(url)
    rows = (await db.execute(
        select(NotebookSource).where(
            NotebookSource.user_id == user_id,
            NotebookSource.kind == "url",
            NotebookSource.file_id.is_not(None))
    )).scalars().all()
    for row in rows:
        if normalize_url(row.ref) == target and row.file_id:
            return row.file_id, "ingested", ""
    try:
        text, _content_type = await fetch_page_text(url)
    except Exception as exc:  # noqa: BLE001 — best-effort ingest
        return None, "failed", str(exc)[:300]
    record = UploadedFile(
        filename=slug_from_url(url),
        stored_path="",
        extension="txt",
        size_bytes=len(text.encode("utf-8")),
        extracted_text=text,
    )
    db.add(record)
    await db.flush()
    try:
        index_document(record.id, text, record.filename)
    except Exception:  # noqa: BLE001 — stored text still retrievable
        pass
    return record.id, "ingested", ""


async def _run_default_transforms(
    db: AsyncSession, notebook: Notebook, source: NotebookSource,
) -> list[dict]:
    """Run apply_default saved transforms over a new source.
    Best-effort: no model configured -> skipped (no error, no fake
    output). Successful outputs become insight rows on the source."""
    defaults = (await db.execute(
        select(NotebookSavedTransform).where(
            NotebookSavedTransform.notebook_id == notebook.id,
            NotebookSavedTransform.apply_default.is_(True))
    )).scalars().all()
    if not defaults:
        return []
    full_text, _note = await _full_source_text(db, source, q="")
    if not full_text:
        return []
    made = []
    for transform in defaults:
        try:
            output = await extract_llm.complete_text(
                db,
                [{"role": "user",
                  "content": f"{transform.prompt}\n\n--- SOURCE ---\n{full_text[:12000]}"}],
                max_tokens=2000,
            )
        except Exception:  # noqa: BLE001 — one bad transform skips
            continue
        if output and output.strip():
            row = NotebookInsight(
                id=_new_id("nbi"), notebook_id=notebook.id,
                user_id=notebook.user_id, source_id=source.id,
                transform_name=transform.name, content=output)
            db.add(row)
            made.append(_insight_out(row))
    return made


async def _context_entries(
    db: AsyncSession, user_id: str, notebook: Notebook, q: str,
    source_ids: list[str] | None = None,
    budget_tokens: int = DEFAULT_CONTEXT_BUDGET_TOKENS,
) -> list[dict]:
    """Build retrieve/transform context honouring context modes AND
    a token budget (open-notebook's context_builder contract, via
    the chars/4 estimate).

    Excluded sources are absent. Summary sources use stored
    summary_text, or the first 500 chars as an extractive fallback
    (labelled). Full sources use full text where available. Texts
    are truncated to the remaining budget with an explicit
    truncation notice that counts against the budget; sources past
    the budget are listed as omitted, never silently dropped. Notes
    in the notebook are always included as full-text entries — they
    are user-authored notebook content, not external sources.
    """
    budget = max(0, int(budget_tokens))
    used = 0

    def _fit(text: str, mode: str) -> tuple[str | None, str | None]:
        """Truncate ``text`` to the remaining budget. Returns
        (fitted text or None, note or None)."""
        nonlocal used
        if budget <= 0:
            return None, "omitted: token budget exhausted"
        est = _estimate_tokens(text)
        if used + est <= budget:
            used += est
            return text, None
        remaining = budget - used
        if remaining <= 0:
            return None, "omitted: token budget exhausted"
        notice = f"[truncated to token budget: {budget} tokens]"
        notice_tokens = _estimate_tokens(notice)
        chars = max(0, (remaining - notice_tokens) * 4)
        fitted = text[:chars] + "\n" + notice
        used = budget
        return fitted, notice

    sources = (await db.execute(
        select(NotebookSource).where(
            NotebookSource.user_id == user_id,
            NotebookSource.notebook_id == notebook.id)
        .order_by(NotebookSource.created_at, NotebookSource.id)
    )).scalars().all()
    entries: list[dict] = []
    for source in sources:
        if source_ids is not None and source.id not in source_ids:
            continue
        if source.context_mode == "excluded":
            continue
        full_text, unavailable = await _full_source_text(db, source, q)
        if source.context_mode == "summary":
            if source.summary_text:
                fitted, note = _fit(source.summary_text, "summary")
                entry = {"source_id": source.id, "kind": source.kind,
                         "ref": source.ref, "mode": "summary"}
                if fitted is not None:
                    entry["text"] = fitted
                if note:
                    entry["note"] = note
                entries.append(entry)
            elif full_text:
                fitted, note = _fit(full_text[:500], "summary")
                entry = {"source_id": source.id, "kind": source.kind,
                         "ref": source.ref, "mode": "summary"}
                if fitted is not None:
                    entry["text"] = fitted
                    entry["note"] = "extractive fallback: first 500 characters"
                    if note:
                        entry["note"] += f"; {note}"
                elif note:
                    entry["note"] = note
                entries.append(entry)
            else:
                entries.append({"source_id": source.id, "kind": source.kind,
                                "ref": source.ref, "mode": "summary",
                                "note": unavailable})
        else:  # full
            if full_text is not None:
                fitted, note = _fit(full_text, "full")
                entry = {"source_id": source.id, "kind": source.kind,
                         "ref": source.ref, "mode": "full"}
                if fitted is not None:
                    entry["text"] = fitted
                if note:
                    entry["note"] = note
                entries.append(entry)
            else:
                entries.append({"source_id": source.id, "kind": source.kind,
                                "ref": source.ref, "mode": "full",
                                "note": unavailable})
    notes = (await db.execute(
        select(NotebookNote).where(
            NotebookNote.user_id == user_id,
            NotebookNote.notebook_id == notebook.id)
        .order_by(NotebookNote.created_at, NotebookNote.id)
    )).scalars().all()
    for note in notes:
        fitted, note_text = _fit(note.content or "", "full")
        entry = {"note_id": note.id, "kind": "note", "ref": note.title,
                 "mode": "full"}
        if fitted is not None:
            entry["text"] = fitted
        if note_text:
            entry["note"] = note_text
        entries.append(entry)
    return entries


# ---------------------------------------------------------------- notebooks

class NotebookIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class NotebookUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


@router.post("/notebooks", status_code=201)
async def create_notebook(
    payload: NotebookIn, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    row = Notebook(id=_new_id("nb"), user_id=user.id, name=payload.name,
                   description=payload.description or "")
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _nb_out(row)


@router.get("/notebooks")
async def list_notebooks(
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    rows = (await db.execute(
        select(Notebook).where(Notebook.user_id == user.id)
        .order_by(desc(Notebook.created_at), desc(Notebook.id))
    )).scalars().all()
    return {"notebooks": [_nb_out(r) for r in rows]}


@router.get("/notebooks/{nb_id}")
async def get_notebook(
    nb_id: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    return _nb_out(await _get_notebook(db, user.id, nb_id))


@router.put("/notebooks/{nb_id}")
async def update_notebook(
    nb_id: str, payload: NotebookUpdateIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    row = await _get_notebook(db, user.id, nb_id)
    if payload.name is not None:
        row.name = payload.name
    if payload.description is not None:
        row.description = payload.description
    row.updated_at = _now()
    await db.commit()
    await db.refresh(row)
    return _nb_out(row)


@router.delete("/notebooks/{nb_id}")
async def delete_notebook(
    nb_id: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    row = await _get_notebook(db, user.id, nb_id)
    for table in (NotebookSource, NotebookNote, NotebookTransform,
                  NotebookSavedTransform, NotebookInsight):
        rows = (await db.execute(
            select(table).where(table.notebook_id == row.id)
        )).scalars().all()
        for child in rows:
            await db.delete(child)
    await db.delete(row)
    await db.commit()
    return {"deleted": nb_id}


# ------------------------------------------------------------------ sources

class SourceIn(BaseModel):
    kind: Literal["file", "url", "note", "chat"]
    ref: str = Field(min_length=1, max_length=512)
    context_mode: Literal["excluded", "summary", "full"] = "full"
    summary_text: str = ""


@router.post("/notebooks/{nb_id}/sources", status_code=201)
async def add_notebook_source(
    nb_id: str, payload: SourceIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    notebook = await _get_notebook(db, user.id, nb_id)
    # kind=file: ref must be an existing knowledge file_id.
    if payload.kind == "file" and await db.get(UploadedFile, payload.ref) is None:
        raise HTTPException(status_code=404, detail="Knowledge file not found")
    # kind=chat: ref must be an existing chat_id.
    if payload.kind == "chat" and await db.get(Chat, payload.ref) is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    # kind=note: ref must be a note in this notebook.
    if payload.kind == "note":
        note = await db.get(NotebookNote, payload.ref)
        if note is None or note.notebook_id != notebook.id:
            raise HTTPException(status_code=404, detail="Note not found in this notebook")
    # kind=url: ref is the URL string itself. Dedupe within the
    # notebook: the same normalized URL returns its existing row.
    if payload.kind == "url":
        if not (payload.ref.startswith("http://") or payload.ref.startswith("https://")):
            raise HTTPException(status_code=422, detail="URL sources need an http(s) URL as ref")
        target = normalize_url(payload.ref)
        existing_rows = (await db.execute(
            select(NotebookSource).where(
                NotebookSource.notebook_id == notebook.id,
                NotebookSource.kind == "url")
        )).scalars().all()
        for row in existing_rows:
            if normalize_url(row.ref) == target:
                return _source_out(row)
    row = NotebookSource(
        id=_new_id("nbs"), notebook_id=notebook.id, user_id=user.id,
        kind=payload.kind, ref=payload.ref, context_mode=payload.context_mode,
        summary_text=payload.summary_text or "")
    db.add(row)
    await db.flush()
    # URL ingest-on-add (skipped for excluded sources: nothing to
    # retrieve, and no network call on a row the user hid). A failed
    # fetch records failed status — it never blocks the 201.
    if payload.kind == "url" and payload.context_mode != "excluded":
        file_id, status, error = await _ingest_url_for_source(db, user.id, payload.ref)
        row.file_id = file_id
        row.ingest_status = status
        row.ingest_error = error
    else:
        row.ingest_status = "skipped" if payload.kind == "url" else "n/a"
    await db.commit()
    await db.refresh(row)
    # apply_default saved transforms run over the new source
    # (best-effort; skipped with no model configured).
    if payload.context_mode != "excluded":
        insights = await _run_default_transforms(db, notebook, row)
        if insights:
            await db.commit()
    return _source_out(row)


@router.get("/notebooks/{nb_id}/sources")
async def list_notebook_sources(
    nb_id: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    notebook = await _get_notebook(db, user.id, nb_id)
    rows = (await db.execute(
        select(NotebookSource).where(NotebookSource.notebook_id == notebook.id)
        .order_by(NotebookSource.created_at, NotebookSource.id)
    )).scalars().all()
    return {"sources": [_source_out(r) for r in rows]}


class SourceContextIn(BaseModel):
    context_mode: Literal["excluded", "summary", "full"]


@router.put("/notebooks/{nb_id}/sources/{source_id}/context")
async def set_source_context(
    nb_id: str, source_id: str, payload: SourceContextIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    await _get_notebook(db, user.id, nb_id)
    row = await _get_source(db, user.id, nb_id, source_id)
    row.context_mode = payload.context_mode
    await db.commit()
    await db.refresh(row)
    return _source_out(row)


@router.get("/notebooks/{nb_id}/retrieve")
async def retrieve_notebook(
    nb_id: str, q: str = Query(min_length=1),
    budget_tokens: int = Query(default=DEFAULT_CONTEXT_BUDGET_TOKENS, ge=0),
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    notebook = await _get_notebook(db, user.id, nb_id)
    entries = await _context_entries(db, user.id, notebook, q,
                                     budget_tokens=budget_tokens)
    return {"notebook_id": notebook.id, "query": q,
            "budget_tokens": budget_tokens, "context": entries}


# ------------------------------------------------- saved transforms + insights

class SavedTransformIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1)
    apply_default: bool = False


@router.post("/notebooks/{nb_id}/saved-transforms", status_code=201)
async def create_saved_transform(
    nb_id: str, payload: SavedTransformIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    """Save a reusable prompt transformation for this notebook.
    ``apply_default`` transforms run over each new source on add."""
    notebook = await _get_notebook(db, user.id, nb_id)
    row = NotebookSavedTransform(
        id=_new_id("nbt"), notebook_id=notebook.id, user_id=user.id,
        name=payload.name, prompt=payload.prompt,
        apply_default=payload.apply_default)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _saved_transform_out(row)


@router.get("/notebooks/{nb_id}/saved-transforms")
async def list_saved_transforms(
    nb_id: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    notebook = await _get_notebook(db, user.id, nb_id)
    rows = (await db.execute(
        select(NotebookSavedTransform).where(
            NotebookSavedTransform.notebook_id == notebook.id)
        .order_by(NotebookSavedTransform.created_at, NotebookSavedTransform.id)
    )).scalars().all()
    return {"saved_transforms": [_saved_transform_out(r) for r in rows]}


@router.get("/notebooks/{nb_id}/insights")
async def list_notebook_insights(
    nb_id: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    notebook = await _get_notebook(db, user.id, nb_id)
    rows = (await db.execute(
        select(NotebookInsight).where(NotebookInsight.notebook_id == notebook.id)
        .order_by(desc(NotebookInsight.created_at), desc(NotebookInsight.id))
    )).scalars().all()
    return {"insights": [_insight_out(r) for r in rows]}


@router.post("/notebooks/{nb_id}/insights/{insight_id}/save-as-note", status_code=201)
async def save_insight_as_note(
    nb_id: str, insight_id: str,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    """Promote an insight row into a note (open-notebook
    save-as-note). The note keeps its provenance: the insight's
    transform name is recorded in the title prefix."""
    notebook = await _get_notebook(db, user.id, nb_id)
    insight = await db.get(NotebookInsight, insight_id)
    if insight is None or insight.notebook_id != notebook.id:
        raise HTTPException(status_code=404, detail="Insight not found")
    title = (f"[{insight.transform_name}] Insight" if insight.transform_name
             else "Insight")
    row = NotebookNote(id=_new_id("nbn"), notebook_id=notebook.id,
                       user_id=user.id, title=title, content=insight.content or "")
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await _rebuild_note_index(db, notebook.id)
    return _note_out(row, with_links=True)


# -------------------------------------------------------------------- notes

class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = ""


@router.post("/notebooks/{nb_id}/notes", status_code=201)
async def create_notebook_note(
    nb_id: str, payload: NoteIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    notebook = await _get_notebook(db, user.id, nb_id)
    row = NotebookNote(id=_new_id("nbn"), notebook_id=notebook.id, user_id=user.id,
                       title=payload.title, content=payload.content or "")
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await _rebuild_note_index(db, notebook.id)
    return _note_out(row, with_links=True)


@router.get("/notebooks/{nb_id}/notes")
async def list_notebook_notes(
    nb_id: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    notebook = await _get_notebook(db, user.id, nb_id)
    rows = (await db.execute(
        select(NotebookNote).where(NotebookNote.notebook_id == notebook.id)
        .order_by(NotebookNote.created_at, NotebookNote.id)
    )).scalars().all()
    return {"notes": [_note_out(r, with_links=True) for r in rows]}


@router.get("/notebooks/{nb_id}/notes/{note_id}")
async def get_notebook_note(
    nb_id: str, note_id: str,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    await _get_notebook(db, user.id, nb_id)
    row = await _get_note(db, user.id, nb_id, note_id)
    return _note_out(row, with_links=True)


class FromChatIn(BaseModel):
    chat_id: str = Field(min_length=1, max_length=64)
    message_id: str | None = None


@router.post("/notebooks/{nb_id}/notes/from-chat", status_code=201)
async def note_from_chat(
    nb_id: str, payload: FromChatIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    """Save a chat message as a note. message_id picks one message;
    without it, the chat's latest message is used. 404 when the chat
    or the message is not found."""
    notebook = await _get_notebook(db, user.id, nb_id)
    chat = await db.get(Chat, payload.chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    if payload.message_id:
        message = await db.get(Message, payload.message_id)
        if message is None or message.chat_id != chat.id:
            raise HTTPException(status_code=404, detail="Message not found in this chat")
    else:
        rows = (await db.execute(
            select(Message).where(Message.chat_id == chat.id)
            .order_by(desc(Message.created_at), desc(Message.id)).limit(1)
        )).scalars().all()
        if not rows:
            raise HTTPException(status_code=404, detail="Chat has no messages")
        message = rows[0]
    row = NotebookNote(
        id=_new_id("nbn"), notebook_id=notebook.id, user_id=user.id,
        title=chat.title or "Chat note", content=message.content or "",
        source_chat_id=chat.id, source_message_id=message.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await _rebuild_note_index(db, notebook.id)
    return _note_out(row, with_links=True)


@router.get("/notebooks/{nb_id}/notes/{note_id}/backlinks")
async def get_note_backlinks(
    nb_id: str, note_id: str,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    """Notes linking to this note — an index lookup, not a scan.

    Falls back to the content scan only when the index has no rows
    for the notebook (notes written before indexing existed)."""
    notebook = await _get_notebook(db, user.id, nb_id)
    target = await _get_note(db, user.id, nb_id, note_id)
    idx_rows = (await db.execute(
        select(NoteLinkIndex).where(
            NoteLinkIndex.notebook_id == notebook.id,
            NoteLinkIndex.target_note_id == target.id)
    )).scalars().all()
    if idx_rows:
        ids = {r.source_note_id for r in idx_rows}
        rows = (await db.execute(
            select(NotebookNote).where(NotebookNote.id.in_(ids))
            .order_by(NotebookNote.created_at, NotebookNote.id)
        )).scalars().all()
        return {"note_id": target.id, "title": target.title,
                "backlinks": [_note_out(r, with_links=True) for r in rows],
                "via": "index"}
    rows = (await db.execute(
        select(NotebookNote).where(NotebookNote.notebook_id == notebook.id,
                                   NotebookNote.id != target.id)
        .order_by(NotebookNote.created_at, NotebookNote.id)
    )).scalars().all()
    linking = [r for r in rows if target.title in parse_wiki_links(r.content)]
    return {"note_id": target.id, "title": target.title,
            "backlinks": [_note_out(r, with_links=True) for r in linking],
            "via": "scan"}


class NoteUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = None


@router.put("/notebooks/{nb_id}/notes/{note_id}")
async def update_notebook_note(
    nb_id: str, note_id: str, payload: NoteUpdateIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    """Update a note. A title change renames through
    rename_note_propagate: every linking doc's [[Old Title]] is
    rewritten to [[New Title]] (piped display text preserved), so
    renames never silently orphan links."""
    notebook = await _get_notebook(db, user.id, nb_id)
    target = await _get_note(db, user.id, nb_id, note_id)
    rows = (await db.execute(
        select(NotebookNote).where(NotebookNote.notebook_id == notebook.id)
        .order_by(NotebookNote.created_at, NotebookNote.id)
    )).scalars().all()
    by_id = {r.id: r for r in rows}
    updates_applied = 0
    if payload.title is not None and payload.title != target.title:
        result = rename_note_propagate(
            [{"id": r.id, "title": r.title, "content": r.content or ""}
             for r in rows], target.id, payload.title)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        for upd in result["updates"]:
            by_id[upd["note_id"]].content = upd["new_content"]
            updates_applied += 1
        target.title = payload.title
    if payload.content is not None:
        target.content = payload.content
    await db.commit()
    await db.refresh(target)
    await _rebuild_note_index(db, notebook.id)
    return {"note": _note_out(target, with_links=True),
            "links_rewritten_in": updates_applied}


class ExtractSectionIn(BaseModel):
    header_title: str = Field(min_length=1)
    new_title: str = Field(min_length=1, max_length=200)


@router.post("/notebooks/{nb_id}/notes/{note_id}/extract-section",
             status_code=201)
async def extract_note_section(
    nb_id: str, note_id: str, payload: ExtractSectionIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    """Extract a section into a new note (iwe's extract op): the new
    note gets the section subtree; the source keeps the header with a
    [[NewTitle]] link in place of the body. Missing or ambiguous
    header -> 422, never a partial rewrite."""
    notebook = await _get_notebook(db, user.id, nb_id)
    target = await _get_note(db, user.id, nb_id, note_id)
    result = extract_section(target.content or "", payload.header_title,
                             payload.new_title)
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    target.content = result["updated_source_content"]
    row = NotebookNote(id=_new_id("nbn"), notebook_id=notebook.id,
                       user_id=user.id, title=payload.new_title,
                       content=result["new_note_content"])
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await _rebuild_note_index(db, notebook.id)
    return {"source": _note_out(target, with_links=True),
            "note": _note_out(row, with_links=True)}


@router.get("/notebooks/{nb_id}/notes/{note_id}/expand")
async def expand_note_graph(
    nb_id: str, note_id: str, depth: int = Query(default=2, ge=1, le=4),
    max_tokens: int = Query(default=4000, ge=100, le=20000),
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    """Token-budgeted graph-expansion retrieval from a seed note:
    seeds expand along links + backlinks to ``depth`` levels;
    periphery is trimmed first, seeds are never trimmed."""
    notebook = await _get_notebook(db, user.id, nb_id)
    await _get_note(db, user.id, nb_id, note_id)
    rows = (await db.execute(
        select(NotebookNote).where(NotebookNote.notebook_id == notebook.id)
    )).scalars().all()
    idx = (await db.execute(
        select(NoteLinkIndex).where(NoteLinkIndex.notebook_id == notebook.id)
    )).scalars().all()
    return expand_retrieval(
        {r.id: {"id": r.id, "title": r.title, "content": r.content or ""}
         for r in rows},
        [{"source_note_id": r.source_note_id,
          "target_note_id": r.target_note_id} for r in idx],
        seeds=[note_id], depth=depth, max_tokens=max_tokens)


# --------------------------------------------------------------- transforms

class TransformIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1)
    source_ids: list[str] | None = None


@router.post("/notebooks/{nb_id}/transforms", status_code=201)
async def run_notebook_transform(
    nb_id: str, payload: TransformIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    """Render prompt + selected source texts through the default model.
    Stores the output as a transform AND as a note (never ephemeral).
    No model -> 503, never fake output."""
    notebook = await _get_notebook(db, user.id, nb_id)
    entries = await _context_entries(db, user.id, notebook, q="",
                                     source_ids=payload.source_ids)
    blocks = []
    for entry in entries:
        if entry.get("text"):
            label = entry.get("ref", entry.get("kind", "source"))
            blocks.append(f"[{entry['kind']}: {label}]\n{entry['text']}")
    context = "\n\n".join(blocks) if blocks else "(no source texts available)"
    try:
        output = await extract_llm.complete_text(
            db,
            [{"role": "user",
              "content": f"{payload.prompt}\n\n--- SOURCES ---\n{context}"}],
            max_tokens=4000,
        )
    except Exception as exc:  # noqa: BLE001 — provider failure is a 503
        raise HTTPException(
            status_code=503, detail=f"No transform available: model call failed ({exc})") from exc
    if output is None or not output.strip():
        raise HTTPException(
            status_code=503,
            detail="No model is configured, so transforms are unavailable.")
    transform = NotebookTransform(
        id=_new_id("nbt"), notebook_id=notebook.id, user_id=user.id,
        name=payload.name, prompt=payload.prompt, output=output,
        source_ids=json.dumps(payload.source_ids or []))
    db.add(transform)
    note = NotebookNote(
        id=_new_id("nbn"), notebook_id=notebook.id, user_id=user.id,
        title=payload.name, content=output)
    db.add(note)
    # Insight rows: the transform output is also recorded per
    # source, so it can be promoted to a note independently of the
    # transform's own note (insight != note, open-notebook shape).
    insight_source_ids = payload.source_ids or [e.get("source_id") for e in entries if e.get("source_id")]
    if insight_source_ids:
        for sid in insight_source_ids:
            db.add(NotebookInsight(
                id=_new_id("nbi"), notebook_id=notebook.id, user_id=user.id,
                source_id=sid, transform_name=payload.name, content=output))
    else:
        db.add(NotebookInsight(
            id=_new_id("nbi"), notebook_id=notebook.id, user_id=user.id,
            source_id=None, transform_name=payload.name, content=output))
    await db.commit()
    await db.refresh(transform)
    await db.refresh(note)
    await _rebuild_note_index(db, notebook.id)
    return {"transform": _transform_out(transform),
            "note": _note_out(note, with_links=True)}


@router.get("/notebooks/{nb_id}/transforms")
async def list_notebook_transforms(
    nb_id: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    notebook = await _get_notebook(db, user.id, nb_id)
    rows = (await db.execute(
        select(NotebookTransform).where(NotebookTransform.notebook_id == notebook.id)
        .order_by(desc(NotebookTransform.created_at), desc(NotebookTransform.id))
    )).scalars().all()
    return {"transforms": [_transform_out(r) for r in rows]}
