"""
api_routes/knowledge_routes.py — knowledge graph API (Phase 3),
plus Wave-2 deep-knowledge: corrective RAG + deep crawl.

Corrective RAG (on GET /knowledge/retrieve): after hybrid retrieval,
the top score is graded against a threshold (deterministic grade
by default; an LLM grade is available behind the ``llm_grade`` flag
and never fakes a score when no model is configured). On weak
evidence the query is rewritten (stopword-stripped) and retrieval
retries; only when still weak AND ``web_fallback`` is set does the
endpoint fall back to web search. The response always shows
``grade`` + ``fallback_used`` and each citation carries its grade,
so a weak answer is visible, not silent.
"""
from fastapi import Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..code_graph import build_graph as build_code_graph
from ..database import get_db
from ..knowledge_graph import build_knowledge_graph
from ..models import Chat, UploadedFile as UserFile
from .common import router


# ---------------------------------------------------------- corrective RAG

def grade_results(results: list[dict], threshold: float = 0.35) -> tuple[str, float]:
    """Deterministic evidence grade: the top hybrid score against
    the threshold. Empty results grade "weak" with score 0.0 —
    absence of evidence is weak evidence, not an error."""
    if not results:
        return "weak", 0.0
    top = max((float(r.get("score") or 0.0) for r in results), default=0.0)
    return ("strong" if top >= threshold else "weak"), top


def rewrite_query(query: str) -> str:
    """Deterministic query rewrite for the corrective retry:
    stopword-stripped content terms (the hybrid tokenizer's own
    stopword set). Falls back to the original query when nothing
    survives stripping."""
    from ..hybrid_retrieval import tokenize

    terms = tokenize(query)
    return " ".join(terms) if terms else query


async def llm_grade_evidence(
    db: AsyncSession, query: str, results: list[dict],
) -> float | None:
    """LLM grade behind a flag: asks the model for one number in
    [0, 1] rating the evidence for the query. Returns None when no
    model is configured or the output is unparseable — the caller
    then keeps the deterministic grade, never a fabricated one."""
    from ..memory import extract_llm

    if not results:
        return None
    excerpts = "\n".join(
        f"- {(r.get('citation', {}) or {}).get('excerpt', '') or r.get('text', '')[:200]}"
        for r in results[:5])
    try:
        raw = await extract_llm.complete_text(
            db,
            [{"role": "user",
              "content": (f"Rate how well these excerpts answer the query "
                          f"'{query}' with a single number from 0 to 1 "
                          f"and nothing else.\n\n{excerpts}")}],
            max_tokens=50,
        )
    except Exception:  # noqa: BLE001 — grade failure keeps deterministic grade
        return None
    if raw is None:
        return None
    import re as _re

    match = _re.search(r"0?\.\d+|1(?:\.0+)?", raw.strip())
    if not match:
        return None
    try:
        value = float(match.group(0))
    except ValueError:
        return None
    return value if 0.0 <= value <= 1.0 else None


@router.get("/knowledge/graph")
async def get_knowledge_graph(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    include_code: bool = Query(default=False),
    max_nodes: int = Query(default=200, le=500),
    as_of: str | None = Query(default=None),
):
    """Unified knowledge graph: memories, documents, code, chats,
    plus memory-graph relations (entity nodes, predicate edges with
    confidence + source_ref). ``as_of`` (ISO datetime) filters
    relations to those true at that instant; without it, relations
    true right now are shown."""
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

    # Memory-graph relations (as-of filtered; default = now).
    relations = []
    try:
        from datetime import UTC, datetime as _dt
        from ..memory.graph import query_as_of, relation_out
        if as_of:
            try:
                instant = _dt.fromisoformat(as_of.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(
                    status_code=422, detail="as_of must be an ISO datetime")
        else:
            instant = _dt.now(UTC)
        rows = await query_as_of(db, user.id, instant)
        relations = [relation_out(r) for r in rows]
    except HTTPException:
        raise
    except Exception:
        relations = []

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
        relations=relations, as_of=as_of,
    )


@router.get("/knowledge/retrieve")
async def retrieve_knowledge(
    q: str = Query(min_length=1),
    file_ids: str = Query(default=""),
    top_k: int = Query(default=5, ge=1, le=20),
    grade_threshold: float = Query(default=0.35, ge=0.0, le=1.0),
    web_fallback: bool = Query(default=False),
    llm_grade: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Phase 2 hybrid retrieval over uploaded documents, with a
    Wave-2 corrective loop.

    Vector + BM25 fusion with deterministic reranking and per-chunk
    citations (file_id, filename, chunk_index, excerpt, source).
    ``file_ids`` is an optional comma-separated list; with none given,
    it searches all uploaded files (uploads are single-user by design,
    like the rest of the Sangam — see Phase 0 ownership audit). Empty
    index -> empty results, never an error.

    Corrective loop: results are graded (top score vs
    ``grade_threshold``; ``llm_grade`` swaps in an LLM grade when a
    model is configured, else the deterministic grade stands). On
    weak evidence the query is rewritten and retrieval retries once;
    if still weak and ``web_fallback`` is set, web search results are
    appended as ``web`` citations. ``grade`` and ``fallback_used``
    (``none`` | ``query-rewrite`` | ``web-search``) are always in
    the response, and every citation carries its grade.
    """
    from ..rag import retrieve_hybrid_chunks

    ids = [f.strip() for f in file_ids.split(",") if f.strip()]
    if not ids:
        rows = (await db.execute(select(UserFile).limit(200))).scalars().all()
        ids = [f.id for f in rows]
    results = retrieve_hybrid_chunks(q, ids, top_k=top_k) if ids else []
    grade, top_score = grade_results(results, threshold=grade_threshold)
    if llm_grade and results:
        llm_score = await llm_grade_evidence(db, q, results)
        if llm_score is not None:
            top_score = llm_score
            grade = "strong" if llm_score >= grade_threshold else "weak"
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
    web_results: list[dict] = []
    if grade == "weak" and web_fallback:
        try:
            from ..websearch import web_search

            for hit in await web_search(q, max_results=5):
                web_results.append({
                    "text": hit.snippet or hit.title or "",
                    "title": hit.title, "url": hit.url,
                    "citation": {"file_id": "", "filename": "",
                                 "chunk_index": None,
                                 "excerpt": (hit.snippet or "")[:200],
                                 "source": "web"},
                    "source": "web", "score": 0.0,
                })
            if web_results:
                fallback_used = "web-search"
        except Exception:  # noqa: BLE001 — web fallback failure is not fatal
            web_results = []
    for r in results:
        citation = r.get("citation") or {}
        citation["grade"] = grade
        r["citation"] = citation
    return {"query": q, "used_query": used_query, "method": "hybrid",
            "grade": grade, "top_score": round(top_score, 4),
            "fallback_used": fallback_used,
            "results": results, "web_results": web_results}


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
    file_id plus chunk count. Re-ingesting an already-ingested URL
    (same normalized URL -> same slug) returns the existing
    document with ``deduped: true`` instead of a second copy.
    """
    import httpx
    from fastapi import HTTPException

    from ..document import truncate_preview
    from ..ingest_url import (
        FETCH_TIMEOUT_SECONDS,
        MAX_BODY_BYTES,
        IngestUrlError,
        html_to_text,
        normalize_url,
        slug_from_url,
        validate_url,
    )
    from ..rag import index_document

    url = (payload.get("url") or "").strip()
    filename = slug_from_url(url)
    existing = (await db.execute(
        select(UserFile).where(UserFile.filename == filename)
    )).scalars().first()
    if existing is not None and existing.extracted_text:
        return {
            "file_id": existing.id,
            "filename": existing.filename,
            "source_url": url,
            "chars": len(existing.extracted_text),
            "chunks_indexed": 0,
            "preview": truncate_preview(existing.extracted_text),
            "deduped": True,
            "note": "URL already ingested; existing document returned.",
        }
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
        "deduped": False,
        "note": "HTML boilerplate may survive extraction; this is a text stripper, not a reader mode.",
    }


# ------------------------------------------------------------ deep crawl

@router.post("/knowledge/crawl")
async def start_crawl(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """BFS deep crawl into Knowledge (crawl4ai pipeline shape).

    Approval-gated like the browser agent: ``approved: true`` is
    required, otherwise 422 — crawling executes fetches against
    third-party sites and must never run on an ambiguous request.
    SSRF + robots rules from ``backend.crawl_job`` apply to the seed
    and every discovered URL. Each fetched page is stored as a
    document and indexed for hybrid retrieval; ``parent_url``
    provenance is persisted per page (see GET /knowledge/crawls).
    The job is mirrored onto the Runs centre (RunStore) so crawl
    progress is visible alongside other runs. ``allow_local`` exists
    ONLY for local fixture/docs crawls (tests, localhost docs) and
    bypasses the public-address SSRF check; it defaults off.
    ``use_browser`` renders pages through the Node Playwright driver
    (JS sites); link discovery still uses a static fetch until the
    driver gains a ``links`` action.
    """
    import uuid as _uuid

    from ..contracts import RunState, run_store
    from ..crawl_job import (
        DEFAULT_MAX_DEPTH,
        DEFAULT_MAX_PAGES,
        CrawlJob,
        CrawlPage,
        browser_fetcher,
        crawl_job_out,
        crawl_page_out,
        fetch_page_http,
        run_crawl,
    )
    from ..ingest_url import IngestUrlError, slug_from_url, validate_url
    from ..rag import index_document

    seed_url = ((payload or {}).get("seed_url") or "").strip()
    if not seed_url:
        raise HTTPException(status_code=422, detail="seed_url is required")
    if not payload.get("approved"):
        raise HTTPException(
            status_code=422,
            detail="Crawling requires explicit approval: pass approved: true")
    allow_local = bool(payload.get("allow_local", False))
    if not allow_local:
        try:
            validate_url(seed_url)
        except IngestUrlError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    max_depth = int(payload.get("max_depth", DEFAULT_MAX_DEPTH))
    max_pages = int(payload.get("max_pages", DEFAULT_MAX_PAGES))
    if not (0 <= max_depth <= 5):
        raise HTTPException(status_code=422, detail="max_depth must be 0..5")
    if not (1 <= max_pages <= 200):
        raise HTTPException(status_code=422, detail="max_pages must be 1..200")
    keywords = [str(k) for k in (payload.get("keywords") or []) if str(k).strip()]
    include_external = bool(payload.get("include_external", False))
    use_browser = bool(payload.get("use_browser", False))

    job = CrawlJob(id=f"crawl-{_uuid.uuid4().hex[:12]}",
                   user_id=user.id, seed_url=seed_url,
                   max_depth=max_depth, max_pages=max_pages, status="running")
    db.add(job)
    await db.commit()
    await db.refresh(job)
    run_record = run_store.create(kind="crawl", owner_id=user.id,
                                  title=f"Crawl {seed_url}", run_id=job.id)
    try:
        run_store.transition(run_record.run_id, RunState.RUNNING)
    except Exception:  # noqa: BLE001 — mirror is best-effort
        pass

    robots_cache: dict = {}
    if use_browser:
        fetcher = browser_fetcher(robots_cache=robots_cache)
    else:
        async def fetcher(url: str, _cache=robots_cache):
            return await fetch_page_http(url, robots_cache=_cache,
                                         allow_local=allow_local)

    try:
        summary = await run_crawl(
            seed_url, max_depth=max_depth, max_pages=max_pages,
            keywords=keywords, include_external=include_external,
            fetcher=fetcher, validate_discovered=not allow_local)
    except Exception as exc:  # noqa: BLE001 — crawl failure mirrors failed
        job.status = "failed"
        job.error = str(exc)[:500]
        await db.commit()
        try:
            run_store.transition(run_record.run_id, RunState.FAILED)
        except Exception:  # noqa: BLE001
            pass
        raise HTTPException(status_code=502, detail=f"Crawl failed: {exc}") from exc

    response_pages = []
    for page in summary["pages"]:
        text = page.get("text", "")
        record = UserFile(
            filename=slug_from_url(page["url"]), stored_path="",
            extension="txt", size_bytes=len(text.encode("utf-8")),
            extracted_text=text)
        db.add(record)
        await db.flush()
        try:
            index_document(record.id, text, record.filename)
        except Exception:  # noqa: BLE001 — stored text still retrievable
            pass
        db.add(CrawlPage(id=f"cpg-{_uuid.uuid4().hex[:12]}",
                         job_id=job.id, url=page["url"],
                         parent_url=page["parent_url"], depth=page["depth"],
                         file_id=record.id, title=page.get("title", "")))
        response_pages.append({k: v for k, v in page.items() if k != "text"})
        response_pages[-1]["file_id"] = record.id
    job.status = "done"
    job.pages_indexed = len(summary["pages"])
    await db.commit()
    try:
        run_store.transition(run_record.run_id, RunState.SUCCEEDED)
    except Exception:  # noqa: BLE001
        pass
    return {"job": crawl_job_out(job), "pages": response_pages,
            "indexed": len(summary["pages"]), "errors": summary["errors"]}


@router.get("/knowledge/crawls/{job_id}")
async def get_crawl(
    job_id: str, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """A crawl job plus its pages with parent_url provenance."""
    from sqlalchemy import select as _select

    from ..crawl_job import CrawlJob, CrawlPage, crawl_job_out, crawl_page_out

    job = await db.get(CrawlJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    pages = (await db.execute(
        _select(CrawlPage).where(CrawlPage.job_id == job.id)
        .order_by(CrawlPage.depth, CrawlPage.url)
    )).scalars().all()
    return {"job": crawl_job_out(job),
            "pages": [crawl_page_out(p) for p in pages]}


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
