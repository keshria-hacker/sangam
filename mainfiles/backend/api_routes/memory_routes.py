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
    room: str = Field(default="default", max_length=64)
    drawer: str = Field(default="general", max_length=64)


class MemoryOut(BaseModel):
    id: str
    content: str
    kind: str
    importance: float
    chat_id: str = ""
    access_count: int = 0
    created_at: str = ""
    score: float | None = None
    room: str = "default"
    drawer: str = "general"

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
            room=record.room,
            drawer=record.drawer,
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
        room=payload.room,
        drawer=payload.drawer,
    )
    if record is None:
        raise HTTPException(status_code=500, detail="Could not save memory")
    return MemoryOut.from_record(record)


@router.get("/memory/export")
async def export_memories(kind: Literal["episodic", "semantic", "procedural"] | None = None):
    """Export memories as a JSON download (local-first portability).

    Returns stored memories (or one kind) as a JSON array with a
    download filename. Honest limit: the memory store caps listings
    at 200, so an export covers the 200 most-recent memories, not an
    unbounded archive — the same cap the rooms view already uses.
    This is the user's own data leaving through their own
    authenticated session — the same protection as the rest of the
    memory API.
    """
    from fastapi.responses import JSONResponse

    records = await list_memories(kind=MemoryKind(kind) if kind else None, limit=10000)
    payload = [
        {
            "id": r.id,
            "content": r.content,
            "kind": r.kind.value,
            "importance": round(r.importance, 3),
            "room": r.room,
            "drawer": r.drawer,
            "chat_id": r.chat_id,
            "access_count": r.access_count,
            "created_at": r.created_at.isoformat(),
        }
        for r in records
    ]
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": "attachment; filename=sangam-memories.json"},
    )


class MemoryForgetIn(BaseModel):
    kind: Literal["episodic", "semantic", "procedural"] | None = None
    room: str | None = Field(default=None, max_length=64)
    older_than_days: int | None = Field(default=None, ge=1)
    confirm: bool = False


@router.post("/memory/forget")
async def forget_memories(payload: MemoryForgetIn):
    """Bulk forget by filter. Two guards against accidents: at least
    one filter must be given (no wipe-all), and ``confirm: true`` is
    required. Returns the deleted count and ids."""
    from datetime import datetime, timedelta, timezone

    if not payload.confirm:
        raise HTTPException(status_code=422, detail="confirm must be true to bulk-forget memories")
    if payload.kind is None and payload.room is None and payload.older_than_days is None:
        raise HTTPException(status_code=422, detail="At least one filter (kind, room, older_than_days) is required")
    cutoff = None
    if payload.older_than_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=payload.older_than_days)
    records = await list_memories(
        kind=MemoryKind(payload.kind) if payload.kind else None, limit=10000
    )
    deleted: list[str] = []
    for r in records:
        if payload.room is not None and (r.room or "default") != payload.room:
            continue
        if cutoff is not None:
            created = r.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created >= cutoff:
                continue
        if await delete_memory(r.id):
            deleted.append(r.id)
    return {"deleted": len(deleted), "ids": deleted}


@router.get("/memory/dashboard")
async def get_memory_dashboard(older_than_days: int | None = None):
    """Privacy dashboard data: exactly what is stored, in one call.

    Persistent memories (Chroma, via the memory service) are listed
    separately from conversation context (chat messages in SQL):
    deleting a chat removes its messages but does NOT delete
    memories extracted from it — those live here and are removed
    only via per-memory DELETE /memory/{id} or POST /memory/forget.
    ``older_than_days`` (optional) previews how many stored
    memories are older than that many days, so the retention
    control in the UI can show the effect before the user confirms
    a forget. Retention itself runs through the existing
    POST /memory/forget (confirm + filter required) — no second
    deletion path, and no .env-only retention knob: the dashboard
    is the control surface.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, select

    from ..database import get_db as _get_db  # local import: no cycle
    from ..models import Chat as _Chat, Message as _Message

    stats = await memory_stats()
    records = await list_memories(limit=10000)
    rooms: dict[str, dict[str, int]] = {}
    for r in records:
        room = r.room or "default"
        drawer = r.drawer or "general"
        rooms.setdefault(room, {})[drawer] = rooms.get(room, {}).get(drawer, 0) + 1
    older_count = None
    if older_than_days is not None and older_than_days >= 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        older_count = 0
        for r in records:
            created = r.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created < cutoff:
                older_count += 1
    # Conversation-context counts come from the live DB session.
    # The route is mounted on the authenticated router, and this
    # endpoint resolves its own session via the get_db generator.
    chat_count = 0
    message_count = 0
    gen = _get_db()
    try:
        db = await gen.__anext__()
        chat_count = (await db.execute(
            select(func.count()).select_from(_Chat))).scalar() or 0
        message_count = (await db.execute(
            select(func.count()).select_from(_Message))).scalar() or 0
    except Exception:
        pass
    finally:
        try:
            await gen.aclose()
        except Exception:
            pass
    return {
        "stats": stats,
        "total_memories": len(records),
        "rooms": [{"name": room, "drawers": [
            {"name": d, "count": c} for d, c in sorted(drawers.items())],
            "total": sum(drawers.values())}
            for room, drawers in sorted(rooms.items())],
        "memories": [MemoryOut.from_record(r) for r in records[:200]],
        "retention_preview": ({"older_than_days": older_than_days,
                               "would_forget": older_count}
                              if older_count is not None else None),
        "separation": {
            "conversation_context": {
                "stored_as": "chat messages in the SQL database",
                "chat_count": chat_count,
                "message_count": message_count,
                "deleted_when": "its chat is deleted",
            },
            "persistent_memory": {
                "stored_as": "typed memories in the memory store",
                "memory_count": len(records),
                "deleted_when": "only via this dashboard (per-memory delete or bulk forget)",
                "note": "Deleting a chat does not delete memories extracted from it.",
            },
        },
    }


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


class MemoryMoveIn(BaseModel):
    room: str = Field(min_length=1, max_length=64)
    drawer: str = Field(min_length=1, max_length=64)


@router.get("/memory/rooms")
async def get_memory_rooms():
    """Get the rooms/drawers hierarchy with memory counts.

    Returns: {rooms: [{name, drawers: [{name, count}], total}]}
    """
    from ..memory import list_memories

    records = await list_memories(limit=10000)
    rooms: dict[str, dict[str, int]] = {}
    for r in records:
        room = r.room or "default"
        drawer = r.drawer or "general"
        if room not in rooms:
            rooms[room] = {}
        rooms[room][drawer] = rooms[room].get(drawer, 0) + 1

    result = []
    for room_name in sorted(rooms.keys()):
        drawers = [
            {"name": d, "count": c}
            for d, c in sorted(rooms[room_name].items())
        ]
        result.append({
            "name": room_name,
            "drawers": drawers,
            "total": sum(rooms[room_name].values()),
        })
    return {"rooms": result}


@router.get("/memory/rooms/{room}/{drawer}")
async def get_drawer_memories(room: str, drawer: str, limit: int = 50):
    """List memories in a specific room/drawer."""
    from ..memory import list_memories

    records = await list_memories(limit=10000)
    filtered = [r for r in records if (r.room or "default") == room and (r.drawer or "general") == drawer]
    filtered = filtered[: min(max(1, limit), 200)]
    return [MemoryOut.from_record(r) for r in filtered]


@router.put("/memory/{memory_id}/move")
async def move_memory(memory_id: str, payload: MemoryMoveIn):
    """Move a memory to a different room/drawer."""
    from ..memory import get_memory, save_memory, delete_memory

    record = await get_memory(memory_id)
    if not record:
        raise HTTPException(status_code=404, detail="Memory not found")
    # Update room/drawer by re-saving (ChromaDB metadata is immutable on update)
    record.room = payload.room
    record.drawer = payload.drawer
    await delete_memory(memory_id)
    new_record = await save_memory(
        record.content,
        kind=record.kind,
        importance=record.importance,
        chat_id=record.chat_id,
        room=record.room,
        drawer=record.drawer,
    )
    if not new_record:
        raise HTTPException(status_code=500, detail="Could not move memory")
    return MemoryOut.from_record(new_record)
