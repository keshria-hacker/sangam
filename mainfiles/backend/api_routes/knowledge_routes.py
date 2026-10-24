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


@router.get("/knowledge/retrieve")
async def retrieve_knowledge(
    q: str = Query(min_length=1),
    file_ids: str = Query(default=""),
    top_k: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Phase 2 hybrid retrieval over uploaded documents.

    Vector + BM25 fusion with deterministic reranking and per-chunk
    citations (file_id, filename, chunk_index, excerpt, source).
    ``file_ids`` is an optional comma-separated list; with none given,
    it searches all uploaded files (uploads are single-user by design,
    like the rest of Sangam — see Phase 0 ownership audit). Empty
    index -> empty results, never an error.
    """
    from ..rag import retrieve_hybrid_chunks

    ids = [f.strip() for f in file_ids.split(",") if f.strip()]
    if not ids:
        rows = (await db.execute(select(UserFile).limit(200))).scalars().all()
        ids = [f.id for f in rows]
    results = retrieve_hybrid_chunks(q, ids, top_k=top_k) if ids else []
    return {"query": q, "method": "hybrid", "results": results}


@router.post("/knowledge/ingest-url")
async def ingest_url(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Phase 2 remainder: ingest a public web page as a document.

    The URL is SSRF-guarded (see ``backend.ingest_url``), fetched
    without following redirects, stripped to text, stored as an
    UploadedFile and indexed for hybrid retrieval. Returns the new
    file_id plus chunk count. No schema change: the source URL is
    recorded in the stored filename suffix only via the page slug —
    re-ingesting the same URL creates a second copy (documented limit,
    not silently deduped).
    """
    import httpx
    from fastapi import HTTPException

    from ..document import truncate_preview
    from ..ingest_url import (
        FETCH_TIMEOUT_SECONDS,
        MAX_BODY_BYTES,
        IngestUrlError,
        html_to_text,
        slug_from_url,
        validate_url,
    )
    from ..rag import index_document

    url = (payload.get("url") or "").strip()
    try:
        validate_url(url)
    except IngestUrlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(FETCH_TIMEOUT_SECONDS, connect=8.0),
            follow_redirects=False,
        ) as client:
            resp = await client.get(url, headers={"User-Agent": "Sangam/1.0 (+local-first)"})
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not fetch URL") from None
    if resp.status_code in (301, 302, 303, 307, 308):
        raise HTTPException(status_code=422, detail="Redirects are not followed for ingestion")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"URL returned HTTP {resp.status_code}")
    content_type = (resp.headers.get("content-type") or "").lower()
    if "text/html" not in content_type and "text/plain" not in content_type:
        raise HTTPException(status_code=415, detail=f"Unsupported content type: {content_type or 'unknown'}")
    body = resp.content[: MAX_BODY_BYTES + 1]
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Page exceeds 2 MB ingestion limit")
    text = html_to_text(body.decode("utf-8", errors="replace")) if "text/html" in content_type else body.decode("utf-8", errors="replace").strip()
    if not text:
        raise HTTPException(status_code=422, detail="No readable text found on the page")
    filename = slug_from_url(url)
    record = UserFile(
        filename=filename,
        stored_path="",
        extension="txt",
        size_bytes=len(text.encode("utf-8")),
        extracted_text=text,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    chunks = index_document(record.id, text, filename) if text else 0
    return {
        "file_id": record.id,
        "filename": filename,
        "source_url": url,
        "chars": len(text),
        "chunks_indexed": chunks,
        "preview": truncate_preview(text),
        "note": "HTML boilerplate may survive extraction; this is a text stripper, not a reader mode.",
    }


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
