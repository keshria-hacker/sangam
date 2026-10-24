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
- URL sources carry no stored text (the URL string only); ingest the
  page as a document to make it retrievable.
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
from ..memory import extract_llm
from ..models import Chat, Message, UploadedFile
from .common import router

__all__ = [
    "create_notebook", "list_notebooks", "get_notebook", "update_notebook",
    "delete_notebook", "add_notebook_source", "list_notebook_sources",
    "set_source_context", "retrieve_notebook", "create_notebook_note",
    "list_notebook_notes", "get_notebook_note", "note_from_chat",
    "run_notebook_transform", "list_notebook_transforms", "get_note_backlinks",
]

CONTEXT_MODES = ("excluded", "summary", "full")
SOURCE_KINDS = ("file", "url", "note", "chat")
WIKI_RE = re.compile(r"\[\[([^\]]+)\]\]")


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


# -------------------------------------------------------------- serializers

def _nb_out(row: Notebook) -> dict:
    return {"id": row.id, "name": row.name, "description": row.description,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


def _source_out(row: NotebookSource) -> dict:
    return {"id": row.id, "notebook_id": row.notebook_id, "kind": row.kind,
            "ref": row.ref, "context_mode": row.context_mode,
            "summary_text": row.summary_text,
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
    # kind == "url": only the URL string is stored, no fetched text.
    return None, ("URL source has no stored text; ingest the page as a "
                  "document to make it retrievable.")


async def _context_entries(
    db: AsyncSession, user_id: str, notebook: Notebook, q: str,
    source_ids: list[str] | None = None,
) -> list[dict]:
    """Build retrieve/transform context honouring context modes.

    Excluded sources are absent. Summary sources use stored
    summary_text, or the first 500 chars as an extractive fallback
    (labelled). Full sources use full text where available. Notes in
    the notebook are always included as full-text entries — they are
    user-authored notebook content, not external sources.
    """
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
                entries.append({"source_id": source.id, "kind": source.kind,
                                "ref": source.ref, "mode": "summary",
                                "text": source.summary_text})
            elif full_text:
                entries.append({"source_id": source.id, "kind": source.kind,
                                "ref": source.ref, "mode": "summary",
                                "text": full_text[:500],
                                "note": "extractive fallback: first 500 characters"})
            else:
                entries.append({"source_id": source.id, "kind": source.kind,
                                "ref": source.ref, "mode": "summary",
                                "note": unavailable})
        else:  # full
            if full_text is not None:
                entries.append({"source_id": source.id, "kind": source.kind,
                                "ref": source.ref, "mode": "full",
                                "text": full_text})
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
        entries.append({"note_id": note.id, "kind": "note", "ref": note.title,
                        "mode": "full", "text": note.content or ""})
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
    for table in (NotebookSource, NotebookNote, NotebookTransform):
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
    # kind=url: ref is the URL string itself.
    if payload.kind == "url" and not (
            payload.ref.startswith("http://") or payload.ref.startswith("https://")):
        raise HTTPException(status_code=422, detail="URL sources need an http(s) URL as ref")
    row = NotebookSource(
        id=_new_id("nbs"), notebook_id=notebook.id, user_id=user.id,
        kind=payload.kind, ref=payload.ref, context_mode=payload.context_mode,
        summary_text=payload.summary_text or "")
    db.add(row)
    await db.commit()
    await db.refresh(row)
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
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    notebook = await _get_notebook(db, user.id, nb_id)
    entries = await _context_entries(db, user.id, notebook, q)
    return {"notebook_id": notebook.id, "query": q, "context": entries}


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
    return _note_out(row, with_links=True)


@router.get("/notebooks/{nb_id}/notes/{note_id}/backlinks")
async def get_note_backlinks(
    nb_id: str, note_id: str,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    """Notes in the same notebook whose content contains [[this title]]."""
    notebook = await _get_notebook(db, user.id, nb_id)
    target = await _get_note(db, user.id, nb_id, note_id)
    rows = (await db.execute(
        select(NotebookNote).where(NotebookNote.notebook_id == notebook.id,
                                   NotebookNote.id != target.id)
        .order_by(NotebookNote.created_at, NotebookNote.id)
    )).scalars().all()
    linking = [r for r in rows if target.title in parse_wiki_links(r.content)]
    return {"note_id": target.id, "title": target.title,
            "backlinks": [_note_out(r, with_links=True) for r in linking]}


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
    await db.commit()
    await db.refresh(transform)
    await db.refresh(note)
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
