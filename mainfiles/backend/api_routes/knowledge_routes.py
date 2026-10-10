"""
api_routes/knowledge_routes.py — knowledge graph API (Phase 3).
"""
from fastapi import Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..code_graph import build_graph as build_code_graph
from ..database import get_db
from ..knowledge_graph import build_knowledge_graph
from ..models import Chat, UploadedFile as UserFile
from .common import router


@router.get("/knowledge/graph")
async def get_knowledge_graph(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    include_code: bool = Query(default=False),
    max_nodes: int = Query(default=200, le=500),
):
    """Unified knowledge graph: memories, documents, code, chats."""
    # Documents (uploaded files)
    files = (await db.execute(select(UserFile).limit(100))).scalars().all()
    documents = [
        {"id": f.id, "filename": f.filename, "mime_type": f.extension, "size": f.size_bytes}
        for f in files
    ]

    # Chats (same query shape as chats_routes.list_chats — Chat has no user_id column)
    chats = (await db.execute(
        select(Chat).order_by(Chat.updated_at.desc()).limit(50)
    )).scalars().all()
    chat_dicts = [{"id": c.id, "title": c.title, "model": c.model} for c in chats]

    # Memories (via the memory service)
    memories = []
    try:
        from ..memory import get_memory_service
        svc = get_memory_service()
        records = svc.search("", limit=100, user_id=user.id) or []
        memories = [
            {"id": r.id, "content": r.content, "kind": r.kind,
             "importance": getattr(r, "importance", 0)}
            for r in records
        ]
    except Exception:
        pass

    # Code graph (optional, expensive)
    code_g = None
    if include_code:
        try:
            from ..config import settings
            root = getattr(settings, "CODE_ROOT", ".")
            code_g = build_code_graph(root)
        except Exception:
            pass

    return build_knowledge_graph(
        memories=memories, documents=documents,
        code_graph=code_g, chats=chat_dicts, max_nodes=max_nodes,
    )


@router.get("/knowledge/search")
async def search_knowledge(
    q: str = Query(min_length=1),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    limit: int = Query(default=20, le=50),
):
    """Full-text search across memories, documents, and chats."""
    results = []
    ql = q.lower()

    # Memories
    try:
        from ..memory import get_memory_service
        svc = get_memory_service()
        for r in svc.search(q, limit=limit, user_id=user.id) or []:
            results.append({"type": "memory", "id": r.id,
                            "label": (r.content or "")[:120], "score": 1.0})
    except Exception:
        pass

    # Documents by filename
    files = (await db.execute(select(UserFile).limit(200))).scalars().all()
    for f in files:
        if ql in (f.filename or "").lower():
            results.append({"type": "document", "id": f.id,
                            "label": f.filename, "score": 0.8})

    # Chats by title
    chats = (await db.execute(
        select(Chat).where(Chat.user_id == user.id).limit(200)
    )).scalars().all()
    for c in chats:
        if ql in (c.title or "").lower():
            results.append({"type": "chat", "id": c.id,
                            "label": c.title, "score": 0.6})

    return {"query": q, "results": results[:limit]}
