"""
api_routes/chats_routes.py — chat CRUD, user preferences, rolling summary,
and per-message feedback endpoints.
"""
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import llm
from ..auth import get_current_user
from ..database import get_db
from ..models import Chat, Message, UserPreference
from ..schemas import (
    ChatDetailOut,
    ChatOut,
    FeedbackIn,
    UserPreferenceIn,
    UserPreferenceOut,
)
from .common import router


@router.post("/chats", response_model=ChatDetailOut)
async def create_chat(request: Request, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    """Create a new chat."""
    body = await request.json()
    title = body.get("title", "New chat")
    model_id = body.get("model")

    if not model_id:
        raise HTTPException(status_code=400, detail="Model is required")

    model_info = llm._resolve_model(model_id)
    if not model_info:
        raise HTTPException(status_code=400, detail=f"Unknown model: {model_id}")

    chat = Chat(title=title[:60], model=model_id)
    db.add(chat)
    await db.flush()
    await db.commit()
    await db.refresh(chat)

    return ChatDetailOut(
        id=chat.id,
        title=chat.title,
        model=chat.model,
        chat_id=chat.id,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        message_count=0,
    )


@router.get("/chats", response_model=list[ChatOut])
async def list_chats(db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    """List chats newest-first. Messages are loaded with selectinload — a lazy
    load here would raise MissingGreenlet inside the async response loop."""
    result = await db.execute(
        select(Chat).order_by(Chat.updated_at.desc()).limit(100).options(selectinload(Chat.messages))
    )
    chats = result.scalars().unique().all()

    return [
        ChatOut(
            id=chat.id,
            title=chat.title,
            model=chat.model,
            summary=chat.summary,
            created_at=chat.created_at,
            updated_at=chat.updated_at,
            message_count=len(chat.messages),
        )
        for chat in chats
    ]


@router.get("/chats/{chat_id}/export")
async def export_chat(
    chat_id: str,
    format: str = "markdown",
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Export a chat as Markdown (open-webui parity) for download."""
    from fastapi.responses import PlainTextResponse

    if format not in ("markdown", "md"):
        raise HTTPException(status_code=400, detail="Unsupported format (use markdown)")
    result = await db.execute(
        select(Chat).where(Chat.id == chat_id).options(selectinload(Chat.messages))
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    lines = [f"# {chat.title or 'Chat'}", ""]
    created = chat.created_at.isoformat() if chat.created_at else ""
    lines.append(f"_Exported from Sangam · model: {chat.model or '—'} · {created}_")
    lines.append("")
    for msg in sorted(chat.messages, key=lambda m: m.created_at or datetime.min):
        role = "**You**" if msg.role == "user" else "**Assistant**"
        lines.append(f"## {role}")
        lines.append("")
        lines.append(msg.content or "")
        lines.append("")
    markdown = "\n".join(lines).rstrip() + "\n"
    safe_title = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in (chat.title or "chat"))[:60]
    return PlainTextResponse(
        markdown,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{safe_title}.md"'},
    )


@router.get("/chats/{chat_id}", response_model=ChatDetailOut)
async def get_chat(chat_id: str, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    """Get a chat by ID."""
    result = await db.execute(
        select(Chat).where(Chat.id == chat_id).options(selectinload(Chat.messages))
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    return ChatDetailOut(
        id=chat.id,
        title=chat.title,
        model=chat.model,
        chat_id=chat.id,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        message_count=len(chat.messages),
        messages=list(chat.messages),
    )


@router.delete("/chats/{chat_id}", status_code=204)
async def delete_chat(chat_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Chat).where(Chat.id == chat_id).options(selectinload(Chat.messages))
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    await db.delete(chat)
    await db.commit()


# ---------------------------------------------------------------------------
# User preferences (response style)
# ---------------------------------------------------------------------------


@router.get("/user/preferences", response_model=UserPreferenceOut)
async def get_preferences(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Return the caller's stored response-style preferences (defaults if unset)."""
    pref = await db.get(UserPreference, user.id)
    if pref is None:
        # An unpersisted ORM instance would serialize None for every field and
        # fail response validation, so return explicit defaults instead.
        return UserPreferenceOut(
            user_id=user.id,
            response_style="balanced",
            formality="neutral",
            expertise_level="general",
            updated_at=datetime.now(UTC),
        )
    return pref


@router.put("/user/preferences", response_model=UserPreferenceOut)
async def update_preferences(
    body: UserPreferenceIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Create-or-update the caller's response-style preferences (upsert)."""
    pref = await db.get(UserPreference, user.id)
    if pref is None:
        pref = UserPreference(user_id=user.id)
        db.add(pref)
    pref.response_style = body.response_style
    pref.formality = body.formality
    pref.expertise_level = body.expertise_level
    await db.commit()
    await db.refresh(pref)
    return pref


# ---------------------------------------------------------------------------
# Chat summary + message feedback
# ---------------------------------------------------------------------------


@router.get("/chats/{chat_id}/summary")
async def get_chat_summary(chat_id: str, db: AsyncSession = Depends(get_db)):
    """Return the chat's rolling summary and key topics."""
    chat = await db.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {
        "chat_id": chat.id,
        "summary": chat.summary,
        "key_topics": [t for t in (chat.key_topics or "").split(",") if t],
        "summarized_at": chat.summarized_at,
    }


@router.post("/messages/{message_id}/feedback")
async def submit_feedback(
    message_id: str,
    body: FeedbackIn,
    db: AsyncSession = Depends(get_db),
):
    """Record quality feedback (thumbs up/down) on an assistant message.

    Sending the same value again clears the feedback (toggle-off undo), so a
    mis-click is recoverable. A note is optional free-text context.
    """
    msg = await db.get(Message, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")

    if msg.feedback == body.value:
        # Toggle-off: same value twice clears the feedback.
        msg.feedback = None
        msg.feedback_note = None
    else:
        msg.feedback = body.value
        if body.note is not None:
            msg.feedback_note = body.note
    await db.commit()
    return {"status": "ok", "feedback": msg.feedback}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class AppendMessagesIn(BaseModel):
    messages: list[dict]  # [{role, content}]


@router.post("/chats/{chat_id}/messages")
async def append_messages(chat_id: str, payload: AppendMessagesIn,
                          db: AsyncSession = Depends(get_db),
                          current_user=Depends(get_current_user)):
    """Append messages to a chat (used by Agent mode, which bypasses /chat/stream)."""
    chat = (await db.execute(select(Chat).where(Chat.id == chat_id))).scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    saved = []
    for m in payload.messages:
        role = m.get("role", "user")
        content = (m.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        msg = Message(chat_id=chat_id, role=role, content=content,
                      created_at=datetime.now(UTC))
        db.add(msg)
        saved.append(role)
    chat.updated_at = datetime.now(UTC)
    await db.commit()
    return {"ok": True, "saved": saved}
