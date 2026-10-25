"""
api_routes/chat_stream_routes.py — the chat streaming pipeline (SSE).
"""
import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import llm, websearch
from ..auth import get_current_user
from ..capability_orchestration import derive_interpretations, should_clarify
from ..context_manager import create_context_manager
from ..database import AsyncSessionLocal, get_db
from ..domain import ChatMessage
from ..graph_provenance import clear_current_provenance, get_current_provenance
from ..memory import (
    extract_from_turn_background,
    extract_from_turn_llm_background,
    recall,
)
from ..models import Chat, Message, UploadedFile, UserPreference
from ..rag import TOP_K as RAG_TOP_K
from ..rag import retrieve_hybrid_chunks
from ..response_events import (
    ResponseEventBuilder,
    ResponseEventType,
    normalize_error,
)
from ..response_intelligence import analyze_request, build_system_prompt_additions
from ..response_intelligence import config as ri_config
from ..response_postprocessor import post_process_response
from ..schemas import ChatStreamRequest
from ..summarizer import should_summarize, summarize_chat
from .common import (
    _background_tasks,
    logger,
    router,
    sse_event,
    sse_response_event,
)
from .media_routes import media_content_parts, resolve_media_json

# SSE heartbeat interval (seconds) — keeps proxies/load-balancers from timing out
# long-lived streaming connections during slow model generations.
SSE_HEARTBEAT_INTERVAL = 15

# --- Wave-2 message-evidence persistence ---------------------------------
# The stream loop below collects tool calls / citations / artifacts from
# the canonical response events and stores them on the assistant Message
# at the persistence save point, so a reloaded chat returns the same
# evidence the live message showed (previously only role/content
# survived, and the Inspector only worked in-session). Caps keep one
# pathological turn from bloating the messages table. This block only
# reads the provenance tracker at save time; it does not change the
# memory-recall or extraction paths.
_EVIDENCE_TOOL_CALL_LIMIT = 50
_EVIDENCE_CITATION_LIMIT = 100
_EVIDENCE_ARTIFACT_LIMIT = 50


def _evidence_json(items, limit):
    """JSON-encode an evidence list for a Message column, or None if empty."""
    if not items:
        return None
    try:
        return json.dumps(list(items)[:limit])
    except (TypeError, ValueError):
        return None


def _args_text(value):
    """Normalize a tool-call arguments payload to the string the UI renders."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return str(value)


def _event_tool_key(metadata):
    """Tool identity across TOOL_START/DELTA/RESULT events.

    The provider layer emits `tool_call_id`; the frontend controller
    historically used `tool_id` — accept both so a result always lands
    on its own call instead of spawning a duplicate entry.
    """
    meta = metadata if isinstance(metadata, dict) else {}
    return meta.get("tool_call_id") or meta.get("tool_id") or meta.get("id")


def _provenance_citations():
    """Map the current answer's provenance nodes to citation dicts.

    RAG/memory nodes are otherwise only emitted as a post-commit SSE
    `provenance` event and lost on reload; as citations they survive
    and render in the message + Inspector like provider citations.
    """
    try:
        nodes = get_current_provenance().used_nodes
    except Exception:  # noqa: BLE001 — provenance must never break persistence
        return []
    return [
        {
            "title": n.get("label") or n.get("id") or "Source",
            "source_id": n.get("id"),
            "source_type": n.get("type"),
            "reason": n.get("reason") or "",
        }
        for n in nodes if isinstance(n, dict)
    ]

@router.post("/chat/stream")
async def chat_stream(  # noqa: PLR0912
    payload: ChatStreamRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Phase 7: clear provenance tracker for this request.
    clear_current_provenance()
    # Validate the model exists before allocating any resources — a fast 400
    # is much better than failing mid-stream after the chat has been created.
    model_info = llm._resolve_model(payload.model)
    if model_info is None:
        raise HTTPException(status_code=400, detail=f"Unknown model: {payload.model}")

    # Prompt injection detection (warn-only mode — logs but never blocks).
    # See backend/prompt_injection.py for the heuristic detector.
    try:
        from ..prompt_injection import detect_injection
        import logging
        _pi_logger = logging.getLogger("sangam.prompt_injection")
        for m in payload.messages:
            if m.role == "user" and m.content:
                flagged, score, reasons = detect_injection(m.content)
                if flagged:
                    _pi_logger.warning(
                        "Prompt injection detected (score=%.2f): %s",
                        score, "; ".join(reasons[:3]),
                    )
    except Exception:
        pass  # Detector must never break the chat flow

    # Optional web-search augmentation: when the client requests it, fetch live
    # results for the latest user turn and inject them as context so the model
    # can answer with current information. Failures never break the chat — they
    # surface as a notice inside the stream instead.
    web_context = ""
    if getattr(payload, "web_search", False):
        try:
            last_user = next((m.content for m in reversed(payload.messages) if m.role == "user"), "")
            if last_user:
                results = await websearch.web_search(last_user, max_results=payload.web_search_max_results)
                web_context = websearch.format_context(last_user, results)
        except Exception as exc:  # noqa: BLE001 — surface but don't kill the chat
            web_context = f"[Web search unavailable: {exc}]"

    # 1. Resolve or create the chat
    if payload.chat_id:
        chat = await db.get(Chat, payload.chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found")
    else:
        first_user_msg = next((m.content for m in payload.messages if m.role == "user"), "New chat")
        chat = Chat(title=first_user_msg[:60], model=payload.model)
        db.add(chat)
        await db.flush()
        await db.commit()
        await db.refresh(chat)

    # 2. Fold any attached files into the latest user message.
    #    Uses hybrid retrieval (vector + BM25, RRF) when possible;
    #    falls back to the full extracted text stored in the database
    #    on any error or empty result. (A3: the last vector-only
    #    chat path — notebooks and /knowledge/retrieve already used
    #    hybrid; hybrid results carry the same text/filename/file_id
    #    keys this block consumes, plus provenance-labelled citations.)
    messages = [m.model_dump() for m in payload.messages]
    if payload.file_ids:
        result = await db.execute(select(UploadedFile).where(UploadedFile.id.in_(payload.file_ids)))
        files = result.scalars().all()
        if files and messages:
            last_user_msg = messages[-1]["content"]
            rag_chunks = retrieve_hybrid_chunks(last_user_msg, payload.file_ids, top_k=RAG_TOP_K)
            if rag_chunks:
                file_context = "\n\n".join(
                    f"--- From {c['filename']} ---\n{c['text']}" for c in rag_chunks
                )
                # Phase 7: track provenance — which documents were used
                prov = get_current_provenance()
                for c in rag_chunks:
                    prov.mark_used(
                        f"doc:{c.get('file_id', c['filename'])}",
                        "document",
                        c['filename'],
                        reason="RAG chunk used in context",
                    )
            else:
                # Fallback: use full extracted text
                file_context = "\n\n".join(
                    f"--- {f.filename} ---\n{f.extracted_text}" for f in files if f.extracted_text
                )
                prov = get_current_provenance()
                for f in files:
                    if f.extracted_text:
                        prov.mark_used(f"doc:{f.id}", "document", f.filename,
                                       reason="Full document text used in context")
            if file_context:
                messages[-1]["content"] = f"{messages[-1]['content']}\n\n[Attached files]\n{file_context}"
    if web_context and messages:
        # Inject as a system message so the model sees the sources.
        messages.insert(0, {"role": "system", "content": web_context})

    # 2b. Media attachments (image/audio). Persisted on the user message as
    #     media_json; vision-capable models additionally receive OpenAI-style
    #     content_parts, other models get a textual note so nothing breaks.
    user_media_json = resolve_media_json(getattr(payload, "media_ids", None))
    if user_media_json and messages:
        last_user_idx = next(
            (i for i in range(len(messages) - 1, -1, -1) if messages[i].get("role") == "user"),
            None,
        )
        if last_user_idx is not None:
            parts = media_content_parts(user_media_json, messages[last_user_idx]["content"])
            vision = bool(getattr(getattr(model_info, "capabilities", None), "vision", False))
            if parts and vision:
                messages[last_user_idx]["content_parts"] = parts
            else:
                names = ", ".join(
                    a.get("filename", "?") for a in json.loads(user_media_json)
                )
                messages[last_user_idx]["content"] += f"\n\n[Attached media: {names}]"

    # --- Phase 6: Response Intelligence ---
    # Analyze request and inject guidance as system prompt additions.
    # This runs BEFORE streaming starts, so it doesn't affect the event pipeline.
    guidance = None
    if ri_config.ENABLED:
        try:
            guidance = await analyze_request(
                messages=messages,
                model_id=payload.model,
                temperature=payload.temperature,
                chat_id=payload.chat_id,
                db=db,  # Use outer request-scoped db for history lookup
            )

            # Phase 4: stored user preferences OVERRIDE detected style signals.
            # Applied BEFORE build_system_prompt_additions so the injected
            # instructions reflect the user's explicit choice.
            try:
                pref = await db.get(UserPreference, current_user.id)
                if pref is not None and guidance.profile is not None:
                    if pref.response_style == "concise":
                        guidance.profile.user_prefers_concise = True
                        guidance.profile.user_prefers_detailed = False
                        guidance.intent.wants_concise = True
                        guidance.intent.wants_detailed = False
                    elif pref.response_style == "detailed":
                        guidance.profile.user_prefers_concise = False
                        guidance.profile.user_prefers_detailed = True
                        guidance.intent.wants_concise = False
                        guidance.intent.wants_detailed = True
                    if pref.formality != "neutral":
                        guidance.intent.tone = pref.formality
                    if pref.expertise_level == "beginner":
                        guidance.intent.technical_depth = "low"
                    elif pref.expertise_level == "expert":
                        guidance.intent.technical_depth = "high"
            except Exception as exc:  # noqa: BLE001 — prefs must never break chat
                logger.warning("User preference override failed: %s", exc)

            system_additions = build_system_prompt_additions(guidance)
            if system_additions:
                system_content = "\n\n".join(system_additions)
                # Find insertion point: after any existing system messages
                insert_idx = 0
                for i, msg in enumerate(messages):
                    if msg.get("role") == "system":
                        insert_idx = i + 1
                messages.insert(insert_idx, {"role": "system", "content": system_content})
                logger.debug("Injected %d response intelligence guidance additions", len(system_additions))
        except Exception as exc:  # noqa: BLE001 — never break chat for guidance errors
            logger.warning("Response intelligence analysis failed: %s", exc)

    # --- Phase 2: Clarification gate ---
    # Ambiguous short requests are intercepted BEFORE generation: we persist the
    # user turn and return a clarification_request event with interpretation
    # options instead of calling the provider. The client renders option buttons
    # that re-send the chosen interpretation as a new user message.
    if guidance is not None and should_clarify(payload.messages[-1].content, guidance):
        async def clarification_generator():
            request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
            builder = ResponseEventBuilder(
                provider=model_info.provider_id,
                model=payload.model,
                request_id=request_id,
            )
            options = derive_interpretations(payload.messages[-1].content, guidance)
            async with AsyncSessionLocal() as clarify_db:
                try:
                    yield sse_event(chat.id, event="chat_id")
                    if not payload.regenerate:
                        clarify_db.add(Message(
                            chat_id=chat.id,
                            role="user",
                            content=payload.messages[-1].content,
                            file_ids=",".join(payload.file_ids) or None,
                            media_json=user_media_json,
                        ))
                        await clarify_db.commit()
                    # Lifecycle: message_start must precede any content event
                    # (the event builder and the client controller both enforce it).
                    yield sse_response_event(builder.message_start())
                    ev = builder.event(
                        ResponseEventType.CLARIFICATION_REQUEST,
                        content="Your request could mean a few different things. Which did you mean?",
                        metadata={"options": options},
                    )
                    yield sse_response_event(ev)
                    # Terminal events: the client controller treats a canonical
                    # stream without message_end as a transport error, so the
                    # clarification card would be replaced by an error banner.
                    yield sse_response_event(builder.message_end())
                    yield sse_event("[DONE]")
                except (GeneratorExit, asyncio.CancelledError):
                    await clarify_db.rollback()
                    if not payload.chat_id:
                        await clarify_db.execute(delete(Chat).where(Chat.id == chat.id))
                        await clarify_db.commit()
                    return
                except Exception as exc:  # noqa: BLE001
                    await clarify_db.rollback()
                    logger.warning("Clarification stream failed: %s", exc)
                    yield sse_event("Could not start the clarification prompt.", event="error")
                    return
        return StreamingResponse(clarification_generator(), media_type="text/event-stream")

    # --- Phase 5: Cross-session memory ---
    # Retrieve relevant long-term memories and inject as provider context.
    # Placed AFTER response-intelligence analysis and the clarification gate:
    # injecting earlier would pollute the conversation history that the
    # ambiguity heuristic reads (a system message at index 0 makes history
    # non-empty, disabling the no-context branch) and the clarification path
    # never calls the provider so it needs no memory.
    # Ranked recall (similarity × recency × importance × access); the current
    # chat's own memories are excluded. Degrades to no-op on any ChromaDB
    # error (recall never raises).
    if not payload.regenerate:
        try:
            last_user_content = payload.messages[-1].content
            # Deep-memory: hybrid rerank + entity-graph boost. db /
            # graph_user_id feed ONLY the boost — they never filter
            # memories (chat-saved memories carry no user_id).
            records = await recall(
                last_user_content, top_k=3, exclude_chat_id=chat.id,
                db=db, graph_user_id=str(current_user.id),
            )
            if records:
                memory_context = "\n".join(f"- {r.content}" for r in records)
                messages.insert(0, {
                    "role": "system",
                    "content": f"[Long-term memory — relevant past conversations]\n{memory_context}",
                })
                logger.debug("Injected %d long-term memories", len(records))
                # Phase 7: track provenance — which memories were used
                prov = get_current_provenance()
                for r in records:
                    prov.mark_used(
                        f"memory:{r.id}",
                        "memory",
                        (r.content or "")[:80],
                        reason=f"Memory ({r.kind}) recalled into context",
                    )
        except Exception as exc:  # noqa: BLE001 — memory must never break chat
            logger.warning("Memory retrieval failed: %s", exc)

    # --- Deep-memory: ADHD prompt style (opt-in) ---
    # When the user's adhdFriendly setting is on, prepend the ADHD
    # style block as a system message so the model writes in that
    # style for this reply. When off, the prompt path is unchanged.
    # Placed after memory injection and before context truncation so
    # the block is counted by the token budget like any system msg.
    try:
        from ..response_quality.adhd import (
            adhd_style_enabled,
            apply_adhd_style_to_messages,
        )

        _adhd_pref = await db.get(UserPreference, current_user.id)
        _adhd_settings = _adhd_pref.settings_json if _adhd_pref else None
        if adhd_style_enabled(_adhd_settings):
            messages = apply_adhd_style_to_messages(messages)
    except Exception as exc:  # noqa: BLE001 — style must never break chat
        logger.warning("ADHD style injection failed: %s", exc)

    # --- Phase 9 P0: Safe Context Truncation ---
    # Apply token budgeting and safe context truncation after Phase 6 intelligence injection
    # but before provider routing and content compression
    try:
        context_manager = create_context_manager(model_info)
        truncation_result = context_manager.prepare_messages(messages)
        if truncation_result.truncated:
            logger.info("Context truncated for chat %s: removed %d messages, %d -> %d tokens (%.1f%% utilization)",
                        chat.id if 'chat' in locals() else 'unknown',
                        truncation_result.removed_message_count,
                        truncation_result.original_token_count,
                        truncation_result.final_token_count,
                        truncation_result.utilization_pct)
        messages = truncation_result.messages
    except Exception as exc:
        logger.warning("Context manager failed: %s", exc)
        # Continue with original messages if context manager fails

    # 3. Stream the assistant's reply, persisting user + assistant messages atomically
    #    inside the generator so a client disconnect or stream error never leaves
    #    orphaned user messages in the database.
    async def event_generator():  # noqa: PLR0912
        # Use a dedicated session so the outer request-scoped `db` is free for
        # concurrent requests — prevents race conditions with connection pool.
        async with AsyncSessionLocal() as stream_db:
            collected = ""
            # Wave-2 evidence collectors (see module helpers above).
            stream_tool_calls: dict[str, dict] = {}
            stream_citations: list[dict] = []
            stream_artifacts: list[dict] = []
            response_message_id = uuid.uuid4().hex[:12]
            # Use request ID from middleware for correlation (Phase 2)
            request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
            last_heartbeat = time.monotonic()
            stream_started_at = time.monotonic()
            try:
                yield sse_event(chat.id, event="chat_id")

                stream_had_error = False
                async for event in llm.stream_response_events(
                    model_id=payload.model,
                    messages=messages,
                    db=stream_db,
                    temperature=payload.temperature,
                    max_tokens=payload.max_tokens,
                    reasoning_effort=payload.reasoning_effort,
                    message_id=response_message_id,
                    request_id=request_id,
                ):
                    yield sse_response_event(event)

                    # Phase 0: provider telemetry ledger — USAGE events
                    # carry token counts; record them (best-effort, never
                    # break the stream) with latency since stream start.
                    if event.type == ResponseEventType.USAGE and event.usage:
                        try:
                            from ..contracts import telemetry_ledger

                            telemetry_ledger.record(
                                provider=event.provider or "unknown",
                                model=event.model or payload.model,
                                latency_ms=(time.monotonic() - stream_started_at) * 1000.0,
                                input_tokens=event.usage.input_tokens or 0,
                                output_tokens=event.usage.output_tokens or 0,
                                correlation_id=request_id,
                            )
                        except Exception:
                            pass

                    if event.type == ResponseEventType.TEXT_DELTA and event.content:
                        collected += event.content
                    elif event.type == ResponseEventType.REASONING_DELTA and event.content:
                        # Reasoning content is included in canonical event only
                        pass
                    elif event.type == ResponseEventType.TOOL_START:
                        # Wave-2 evidence: record the call; DELTA/RESULT
                        # below fill in arguments/result by tool key.
                        meta = event.metadata if isinstance(event.metadata, dict) else {}
                        key = _event_tool_key(meta) or f"tool-{len(stream_tool_calls)}"
                        stream_tool_calls[key] = {
                            "id": key,
                            "name": meta.get("name") or event.content or "tool",
                            "arguments": _args_text(meta.get("arguments")),
                            "status": "starting",
                        }
                    elif event.type == ResponseEventType.TOOL_INPUT_DELTA:
                        meta = event.metadata if isinstance(event.metadata, dict) else {}
                        tc = stream_tool_calls.get(_event_tool_key(meta) or "")
                        if tc is not None:
                            if event.content:
                                tc["arguments"] = (tc.get("arguments") or "") + event.content
                            if meta.get("arguments") is not None:
                                # Provider-side accumulation is authoritative.
                                tc["arguments"] = _args_text(meta.get("arguments"))
                    elif event.type == ResponseEventType.TOOL_RESULT:
                        meta = event.metadata if isinstance(event.metadata, dict) else {}
                        key = _event_tool_key(meta)
                        tc = stream_tool_calls.get(key or "") if key else None
                        if tc is None:
                            key = key or f"tool-{len(stream_tool_calls)}"
                            tc = {"id": key, "name": meta.get("name") or "tool",
                                  "arguments": "", "status": "completed"}
                            stream_tool_calls[key] = tc
                        tc["result"] = event.content or ""
                        tc["status"] = "completed"
                        if meta.get("error"):
                            tc["error"] = meta["error"]
                    elif event.type == ResponseEventType.CITATION:
                        meta = event.metadata if isinstance(event.metadata, dict) else {}
                        cite = dict(meta)
                        if event.content:
                            cite.setdefault("text", event.content)
                        if not cite.get("title"):
                            cite["title"] = (
                                cite.get("label") or cite.get("filename")
                                or (cite.get("text") or "")[:80] or "Source"
                            )
                        stream_citations.append(cite)
                    elif event.type == ResponseEventType.ARTIFACT_START:
                        meta = event.metadata if isinstance(event.metadata, dict) else {}
                        art = dict(meta)
                        if event.content:
                            art["content"] = event.content
                        stream_artifacts.append(art)
                    elif event.type == ResponseEventType.ARTIFACT_DELTA:
                        meta = event.metadata if isinstance(event.metadata, dict) else {}
                        art = None
                        if meta.get("id") is not None:
                            art = next(
                                (a for a in reversed(stream_artifacts)
                                 if a.get("id") == meta.get("id")), None)
                        if art is None and stream_artifacts:
                            art = stream_artifacts[-1]
                        if art is not None and event.content:
                            art["content"] = (art.get("content") or "") + event.content
                    elif event.type == ResponseEventType.ARTIFACT_END:
                        meta = event.metadata if isinstance(event.metadata, dict) else {}
                        art = None
                        if meta.get("id") is not None:
                            art = next(
                                (a for a in reversed(stream_artifacts)
                                 if a.get("id") == meta.get("id")), None)
                        if art is None and stream_artifacts:
                            art = stream_artifacts[-1]
                        # END carries the final content; it wins over any
                        # START + DELTA accumulation above.
                        if art is not None and event.content:
                            art["content"] = event.content
                    elif event.type == ResponseEventType.ERROR:
                        stream_had_error = True
                        message = event.error.message if event.error else "Provider request failed"
                        # Also emit legacy error event for backward compatibility
                        yield sse_event(message, event="error")
                        await stream_db.rollback()
                        if not payload.chat_id:
                            await stream_db.execute(delete(Chat).where(Chat.id == chat.id))
                            await stream_db.commit()
                        return

                    now = time.monotonic()
                    if now - last_heartbeat >= SSE_HEARTBEAT_INTERVAL:
                        yield f": heartbeat {int(now)}\n\n"
                        last_heartbeat = now

                if stream_had_error:
                    return

                if time.monotonic() - last_heartbeat >= SSE_HEARTBEAT_INTERVAL:
                    yield f": heartbeat {int(time.monotonic())}\n\n"

                response_time = time.monotonic() - stream_started_at

                # Phase 3: uncertainty post-processing — hedge low-confidence
                # factual/analysis answers at PERSISTENCE time only. The live
                # stream the user watched is never mutated; the stored text
                # (and what reloads from history) carries the hedge.
                if guidance is not None and ri_config.UNCERTAINTY_HEDGING_ENABLED:
                    try:
                        # Phase 8 C: user noSlop/adhdFriendly settings override env.
                        _no_slop = None
                        _adhd = None
                        try:
                            from ..models import UserPreference
                            import json as _json2
                            _pref = await stream_db.get(UserPreference, user.id)
                            if _pref and _pref.settings_json:
                                _s = _json2.loads(_pref.settings_json)
                                if 'noSlop' in _s:
                                    _no_slop = bool(_s['noSlop'])
                                if 'adhdFriendly' in _s:
                                    _adhd = bool(_s['adhdFriendly'])
                        except Exception:
                            pass
                        collected = post_process_response(collected, guidance, no_slop=_no_slop, adhd_friendly=_adhd)
                    except Exception as exc:  # noqa: BLE001 — never break persistence
                        logger.warning("Uncertainty post-processing failed: %s", exc)

                if not payload.regenerate:
                    stream_db.add(Message(chat_id=chat.id, role="user",
                                   content=payload.messages[-1].content,
                                   file_ids=",".join(payload.file_ids) or None,
                                   media_json=user_media_json))
                stream_db.add(Message(id=response_message_id, chat_id=chat.id, role="assistant", content=collected,
                               model=payload.model, response_time=response_time,
                               # Wave-2 evidence persistence (save point):
                               # provider citations first, then provenance
                               # nodes (RAG/memory) as citations.
                               tool_calls_json=_evidence_json(
                                   list(stream_tool_calls.values()), _EVIDENCE_TOOL_CALL_LIMIT),
                               citations_json=_evidence_json(
                                   stream_citations + _provenance_citations(),
                                   _EVIDENCE_CITATION_LIMIT),
                               artifacts_json=_evidence_json(
                                   stream_artifacts, _EVIDENCE_ARTIFACT_LIMIT)))
                # Merge the chat into the new session so the model/updated_at
                # changes are tracked and persisted on commit.
                chat.model = payload.model
                chat.updated_at = datetime.now(UTC)
                await stream_db.merge(chat)
                await stream_db.commit()
                # Analytics (opt-in): message sent with model. Never breaks chat.
                try:
                    from ..analytics import events as _ae, record_event as _record

                    await _record(
                        stream_db, current_user.id, _ae.MESSAGE_SENT,
                        {"model": payload.model},
                    )
                except Exception:  # noqa: BLE001
                    pass

                # Memory++: fire-and-forget extraction of durable facts from
                # this turn (preferences, corrections, "remember this").
                # Offline heuristics; never blocks the response.
                # Phase 8 C: gated by the memoryAutoExtract setting.
                if not payload.regenerate:
                    try:
                        from ..models import UserPreference
                        import json as _json
                        pref = await stream_db.get(UserPreference, user.id)
                        auto_extract = True
                        if pref and pref.settings_json:
                            s = _json.loads(pref.settings_json)
                            auto_extract = s.get('memoryAutoExtract', True)
                        if auto_extract:
                            extract_from_turn_background(
                                payload.messages[-1].content, chat_id=chat.id
                            )
                            # Deep-memory: LLM extraction runs in
                            # background AFTER the response streamed
                            # (this block runs post-commit, post-stream),
                            # over both roles with recalled-memory
                            # context. Heuristic stays the fallback
                            # when no model is configured.
                            extract_from_turn_llm_background(
                                messages, collected, chat_id=chat.id
                            )
                    except Exception:
                        # On any error, fall back to extracting (conservative).
                        extract_from_turn_background(
                            payload.messages[-1].content, chat_id=chat.id
                        )
                        extract_from_turn_llm_background(
                            messages, collected, chat_id=chat.id
                        )

                # Phase 5: fire-and-forget rolling summarization. Checked every
                # threshold crossing; failures are logged inside summarize_chat.
                try:
                    if await should_summarize(chat.id, stream_db):
                        summary_task = asyncio.create_task(
                            summarize_chat(chat.id, payload.model, stream_db)
                        )
                        _background_tasks.add(summary_task)
                        summary_task.add_done_callback(_background_tasks.discard)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Summarize trigger failed: %s", exc)

                # Phase 7: emit provenance — which nodes were used in this answer.
                try:
                    prov = get_current_provenance()
                    if prov.used_nodes:
                        import json as _json
                        yield sse_event(_json.dumps(prov.to_dict()), event="provenance")
                except Exception:  # noqa: BLE001 — provenance must never break chat
                    pass

                yield sse_event("[DONE]")
            except (GeneratorExit, asyncio.CancelledError):
                await stream_db.rollback()
                # Clean up orphaned chat if this was a new chat
                if not payload.chat_id:
                    await stream_db.execute(delete(Chat).where(Chat.id == chat.id))
                    await stream_db.commit()
                return
            except Exception as exc:
                await stream_db.rollback()
                # Clean up orphaned chat if this was a new chat
                if not payload.chat_id:
                    await stream_db.execute(delete(Chat).where(Chat.id == chat.id))
                    await stream_db.commit()
                error_builder = ResponseEventBuilder(
                    provider=model_info.provider_id,
                    model=payload.model,
                    message_id=response_message_id,
                    request_id=request_id,
                )
                yield sse_response_event(error_builder.message_start())
                normalized = normalize_error(
                    exc,
                    provider=model_info.provider_id,
                    model=payload.model,
                )
                yield sse_response_event(error_builder.error(normalized))
                yield sse_event(normalized.message, event="error")
                return

    return StreamingResponse(event_generator(), media_type="text/event-stream")
