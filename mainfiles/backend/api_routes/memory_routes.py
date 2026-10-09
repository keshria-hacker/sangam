"""
api_routes/memory_routes.py — long-term memory management API.

MemPalace-inspired: typed memories (episodic/semantic/procedural) with
importance-ranked recall, user-curated via these endpoints.
"""
from __future__ import annotations

from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ..memory import (
    MemoryKind,
    MemoryRecord,
    consolidate,
    delete_memory,
    get_memory,
    list_memories,
    memory_stats,
    recall,
    save_memory,
)
from .common import router


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    kind: Literal["episodic", "semantic", "procedural"] = "semantic"
    importance: float | None = Field(default=None, ge=0.0, le=1.0)


class MemoryOut(BaseModel):
    id: str
    content: str
    kind: str
    importance: float
    chat_id: str = ""
    access_count: int = 0
    created_at: str = ""
    score: float | None = None

    @classmethod
    def from_record(cls, record: MemoryRecord, with_score: bool = False) -> "MemoryOut":
        return cls(
            id=record.id,
            content=record.content,
            kind=record.kind.value,
            importance=round(record.importance, 3),
            chat_id=record.chat_id,
            access_count=record.access_count,
            created_at=record.created_at.isoformat(),
            score=round(record.score, 4) if with_score else None,
        )


@router.get("/memory", response_model=list[MemoryOut])
async def search_memories(
    q: str = "",
    kind: Literal["episodic", "semantic", "procedural"] | None = None,
    limit: int = 20,
):
    """Search memories (q) or list recent ones. Ranked best-first on search."""
    limit = min(max(1, limit), 100)
    kinds = [MemoryKind(kind)] if kind else None
    if q.strip():
        records = await recall(q, top_k=limit, kinds=kinds, touch=False)
        return [MemoryOut.from_record(r, with_score=True) for r in records]
    records = await list_memories(kind=MemoryKind(kind) if kind else None, limit=limit)
    return [MemoryOut.from_record(r) for r in records]


@router.post("/memory", response_model=MemoryOut, status_code=201)
async def create_memory(payload: MemoryIn):
    """Explicitly save a memory (the user telling Sangam to remember)."""
    record = await save_memory(
        payload.content,
        kind=MemoryKind(payload.kind),
        importance=payload.importance if payload.importance is not None else 0.9,
    )
    if record is None:
        raise HTTPException(status_code=500, detail="Could not save memory")
    return MemoryOut.from_record(record)


@router.get("/memory/stats")
async def get_memory_stats():
    """Totals by kind for the settings UI."""
    return await memory_stats()


@router.delete("/memory/{memory_id}")
async def remove_memory(memory_id: str):
    """Forget one memory by id."""
    record = await get_memory(memory_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    if not await delete_memory(memory_id):
        raise HTTPException(status_code=500, detail="Could not delete memory")
    return {"deleted": memory_id}


@router.post("/memory/consolidate")
async def run_consolidation():
    """Decay stale memories and prune dead ones. Safe to run on a schedule."""
    return await consolidate()
