"""
api_routes/memory_v2_routes.py — Batch 4: Memory V2.

Routes (mounted under /api by main.py; importing this module registers
the handlers on the shared router AND the graph/transcript tables on
Base.metadata):

  POST   /memory/extract                  LLM fact extraction (on-demand only)
  GET    /memory/entities                 list entities
  GET    /memory/entities/{name}/timeline entity timeline (open + closed)
  POST   /memory/entities/extract         LLM extraction + entity/relation upsert
  POST   /memory/transcripts              store a verbatim message (no cap)
  GET    /memory/transcripts              list transcripts, newest first
  PUT    /memory/{memory_id}              PATCH-style memory update
  POST   /memory/reflect                  synthesize over recalled memories

Honest limits (see also memory/extract_llm.py):
- LLM extraction IS wired into chat: after a streamed reply,
  chat_stream_routes.py runs extract_from_turn_llm_background over
  the turn (heuristic auto-extraction stays the fallback when no
  model is configured). The on-demand endpoints below remain
  available for explicit extraction.
- Reflect / transforms return 503 when no model is configured — never
  a canned fake reflection.
- The entities/extract heuristic fallback extracts Capitalized phrases
  only and says so in the response; it never pretends to be LLM output.
"""
from __future__ import annotations

import json
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..memory import extract_llm
from ..memory.retrieval import recall
from ..memory.store import get_memory, update_memory
from ..memory.graph import (
    MemoryEntity,
    add_relation,
    entity_out,
    entity_timeline,
    list_entities,
    relation_out,
    upsert_entity,
)
from ..memory.transcripts import (
    MemoryTranscript,
    list_transcripts,
    save_transcript,
    transcript_out,
)
from .common import router

# Re-exported so api.py's import block (and tests) can reference them.
__all__ = [
    "extract_memory_llm",
    "list_memory_entities",
    "get_entity_timeline",
    "extract_entities",
    "create_transcript",
    "list_transcript_rows",
    "reflect_memories",
    "update_memory_endpoint",
]


async def _resolve_text(
    db: AsyncSession, user_id: str, text: str, transcript_id: str | None
) -> str:
    """Explicit text wins; otherwise load the transcript's full text."""
    if text.strip():
        return text.strip()
    if transcript_id:
        row = await db.get(MemoryTranscript, transcript_id)
        if not row or row.user_id != user_id:
            raise HTTPException(status_code=404, detail="Transcript not found")
        return row.text or ""
    return ""


class ExtractIn(BaseModel):
    text: str = ""
    chat_id: str = ""
    transcript_id: str | None = None


@router.post("/memory/extract")
async def extract_memory_llm(
    payload: ExtractIn, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """On-demand LLM fact extraction. Saves facts as semantic memories
    and returns them. No model -> empty facts + model_used=false."""
    text = await _resolve_text(db, user.id, payload.text, payload.transcript_id)
    if not text:
        raise HTTPException(status_code=422, detail="text or transcript_id is required")
    result = await extract_llm.extract_facts_llm(
        text, db, chat_id=payload.chat_id, user_id=user.id)
    return {
        "facts": result["facts"], "entities": result["entities"],
        "relations": result["relations"], "saved": result["saved"],
        "model_used": result["model_used"],
    }


@router.get("/memory/entities")
async def list_memory_entities(
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    rows = await list_entities(db, user.id)
    return {"entities": [entity_out(r) for r in rows]}


@router.get("/memory/entities/{name}/timeline")
async def get_entity_timeline(
    name: str, db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    from sqlalchemy import select

    entity = (await db.execute(
        select(MemoryEntity).where(
            MemoryEntity.user_id == user.id, MemoryEntity.name == name)
    )).scalars().first()
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    rows = await entity_timeline(db, user.id, name)
    return {"entity": entity_out(entity),
            "relations": [relation_out(r) for r in rows]}


class EntitiesExtractIn(BaseModel):
    text: str = ""
    transcript_id: str | None = None


@router.post("/memory/entities/extract")
async def extract_entities(
    payload: EntitiesExtractIn, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """LLM extraction + entity/relation upsert. Without a configured
    model, falls back to Capitalized-phrase entities only and says so
    (``fallback: "heuristic-capitalized"``) — never fake LLM output."""
    text = await _resolve_text(db, user.id, payload.text, payload.transcript_id)
    if not text:
        raise HTTPException(status_code=422, detail="text or transcript_id is required")
    result = await extract_llm.extract_facts_llm(text, db, user_id=user.id)
    if not result["model_used"]:
        names = extract_llm.extract_capitalized_entities(text)
        entities = []
        for name in names:
            row = await upsert_entity(db, user.id, name, kind="other")
            entities.append(entity_out(row))
        await db.commit()
        return {
            "entities": entities, "relations": [],
            "fallback": "heuristic-capitalized",
            "note": ("No model is configured, so entities were extracted "
                     "heuristically (Capitalized phrases only) — this is "
                     "not LLM output."),
            "model_used": False,
        }
    entities: dict[str, dict] = {}
    for ent in result["entities"]:
        row = await upsert_entity(db, user.id, ent["name"], kind=ent["kind"])
        entities[row.name] = entity_out(row)
    relations = []
    for rel in result["relations"]:
        # Subjects/objects become entities too, so timelines resolve.
        for side in (rel["subject"], rel["object"]):
            if side not in entities:
                row = await upsert_entity(db, user.id, side, kind="other")
                entities[row.name] = entity_out(row)
        row = await add_relation(
            db, user.id, rel["subject"], rel["predicate"], rel["object"])
        relations.append(relation_out(row))
    await db.commit()
    return {"entities": list(entities.values()), "relations": relations,
            "saved_facts": result["saved"], "model_used": True}


class TranscriptIn(BaseModel):
    chat_id: str = Field(min_length=1, max_length=64)
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1)


@router.post("/memory/transcripts", status_code=201)
async def create_transcript(
    payload: TranscriptIn, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Store one verbatim message. Full text — deliberately NO cap."""
    row = await save_transcript(
        db, user.id, payload.chat_id, payload.role, payload.text)
    await db.commit()
    await db.refresh(row)
    return transcript_out(row)


@router.get("/memory/transcripts")
async def list_transcript_rows(
    chat_id: str = "", limit: int = 50,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    rows = await list_transcripts(db, user.id, chat_id=chat_id, limit=limit)
    return {"transcripts": [transcript_out(r) for r in rows]}


class MemoryUpdateIn(BaseModel):
    content: str | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    room: str | None = Field(default=None, max_length=64)
    drawer: str | None = Field(default=None, max_length=64)


@router.put("/memory/{memory_id}")
async def update_memory_endpoint(
    memory_id: str, payload: MemoryUpdateIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    """PATCH-style update: absent fields keep old values. 404 if absent."""
    existing = await get_memory(memory_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    updated = await update_memory(
        memory_id, content=payload.content, importance=payload.importance,
        room=payload.room, drawer=payload.drawer)
    if updated is None:
        raise HTTPException(status_code=500, detail="Could not update memory")
    return {
        "id": updated.id, "content": updated.content,
        "kind": updated.kind.value, "importance": round(updated.importance, 3),
        "chat_id": updated.chat_id, "access_count": updated.access_count,
        "created_at": updated.created_at.isoformat(),
        "room": updated.room, "drawer": updated.drawer,
    }


REFLECT_SYSTEM = (
    "You synthesize over recalled memories. Return ONLY a JSON object "
    "with exactly these keys: "
    '"observations": [{"text": string, "evidence": [memory ids]}], '
    '"mental_model": string, "open_questions": [strings]. '
    "Every observation MUST cite evidence ids from the memories given, "
    "and nowhere else. Do not invent memories, ids, or facts. If the "
    "memories do not support a claim, say so in an open question."
)


def _parse_reflection(raw: str | None, valid_ids: set[str]) -> dict | None:
    """Parse reflect JSON; evidence ids are filtered to recalled ids.
    Returns None when the output is unparseable (caller answers 503)."""
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(raw[start:end + 1])
        except (ValueError, TypeError):
            return None
    if not isinstance(data, dict):
        return None
    observations = []
    if isinstance(data.get("observations"), list):
        for item in data["observations"][:20]:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                evidence = [e for e in item.get("evidence", [])
                            if isinstance(e, str) and e in valid_ids]
                observations.append({"text": item["text"].strip(), "evidence": evidence})
    mental_model = data.get("mental_model") if isinstance(data.get("mental_model"), str) else ""
    questions = [q.strip() for q in data.get("open_questions", [])
                 if isinstance(q, str) and q.strip()][:20]
    if not observations and not mental_model.strip() and not questions:
        return None
    return {"observations": observations, "mental_model": mental_model.strip(),
            "open_questions": questions}


class ReflectIn(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


@router.post("/memory/reflect")
async def reflect_memories(
    payload: ReflectIn, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Reason over recalled memories + entity timelines. READ-ONLY:
    the synthesis is returned with evidence ids, proof counts, and
    trend — it is never written back as a memory (writing a reflection
    polluted recall with its own synthesis). No model configured ->
    503 with a plain message, never a canned reflection."""
    from ..reflection import reflect_read_only

    records = await recall(payload.query, user_id=user.id,
                           top_k=payload.top_k, touch=False)
    valid_ids = {r.id for r in records}
    memory_lines = [
        f"- [{r.id}] ({r.kind.value}) {r.content}" for r in records
    ]
    # Entity timeline context for entities named in the query.
    timeline_lines: list[str] = []
    for entity in await list_entities(db, user.id):
        if entity.name.lower() in payload.query.lower():
            for rel in await entity_timeline(db, user.id, entity.name):
                window = (f"{rel.valid_from.isoformat()} -> "
                          f"{rel.valid_to.isoformat() if rel.valid_to else 'open'}")
                timeline_lines.append(
                    f"- {rel.subject} {rel.predicate} {rel.object} [{window}]")
    context = "\n".join(memory_lines) if memory_lines else "(no memories recalled)"
    if timeline_lines:
        context += "\nEntity timelines:\n" + "\n".join(timeline_lines)
    try:
        raw = await extract_llm.complete_text(
            db,
            [{"role": "system", "content": REFLECT_SYSTEM},
             {"role": "user",
              "content": f"Query: {payload.query}\n\nMemories:\n{context}"}],
            max_tokens=2000,
        )
    except Exception as exc:  # noqa: BLE001 — provider failure is a 503, not fake content
        raise HTTPException(
            status_code=503, detail=f"No reflection available: model call failed ({exc})") from exc
    if raw is None:
        raise HTTPException(
            status_code=503,
            detail="No model is configured, so reflection is unavailable.")
    result = reflect_read_only(
        [{"id": r.id, "created_at": r.created_at} for r in records], raw)
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="Model output could not be parsed as a reflection; nothing was stored.")
    return result
