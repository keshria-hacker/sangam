"""
summarizer.py — Lightweight session summarizer (Implementation Plan Phase 5).

Called after assistant replies once a chat crosses MESSAGE_THRESHOLD
messages (checked every threshold so long chats keep rolling). Produces a
short structured summary, stores it on the Chat row and in the cross-session
memory vector store.

Failure contract: summarization is best-effort. Every failure is caught and
logged; callers fire-and-forget via asyncio.create_task.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .llm import stream_completion
from .memory import store_memory
from .models import Chat, Message

logger = logging.getLogger(__name__)

# Summarize when a chat crosses N messages (checked with modulo so the
# threshold re-triggers every N messages in long conversations).
MESSAGE_THRESHOLD = 20

SUMMARIZE_PROMPT = """You are a concise conversation summarizer.
Given this conversation history, produce a 2-3 sentence summary covering:
1. The main topic or task
2. Key decisions or conclusions reached
3. Any open questions remaining

Be specific. Output only the summary text, no labels or formatting."""


async def should_summarize(chat_id: str, db: AsyncSession) -> bool:
    """True when the chat's message count crossed the latest threshold."""
    try:
        count = await db.scalar(
            select(func.count(Message.id)).where(Message.chat_id == chat_id)
        )
        return bool(count) and count % MESSAGE_THRESHOLD == 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("should_summarize check failed: %s", exc)
        return False


async def summarize_chat(chat_id: str, model_id: str, db: AsyncSession) -> str | None:
    """Generate and persist a summary for the chat. Returns it, or None on failure."""
    try:
        result = await db.execute(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.created_at)
        )
        messages = result.scalars().all()
        if not messages:
            return None

        # Condense the most recent window (older context is reflected in the
        # existing rolling summary when present).
        chat = await db.get(Chat, chat_id)
        convo = "\n".join(
            f"{m.role.upper()}: {(m.content or '')[:300]}" for m in messages[-20:]
        )
        if chat and chat.summary:
            convo = f"[Previous summary]\n{chat.summary}\n\n[New messages]\n{convo}"

        summary_messages = [
            {"role": "system", "content": SUMMARIZE_PROMPT},
            {"role": "user", "content": convo},
        ]

        summary_text = ""
        async for chunk in stream_completion(
            model_id=model_id,
            messages=summary_messages,
            db=db,
            temperature=0.3,
            max_tokens=200,
        ):
            if isinstance(chunk, str):
                summary_text += chunk

        summary_text = summary_text.strip()
        if not summary_text:
            logger.info("summarize_chat(%s): model returned empty summary", chat_id)
            return None

        # Naive topic extraction: most common meaningful words in user turns.
        key_topics = _extract_topics(messages)

        if chat:
            chat.summary = summary_text
            chat.key_topics = ",".join(key_topics)[:500] or None
            chat.summarized_at = datetime.now(UTC)
            await db.commit()

        await store_memory(chat_id=chat_id, summary=summary_text, key_topics=key_topics)
        logger.info("summarize_chat(%s): stored summary (%d chars)", chat_id, len(summary_text))
        return summary_text
    except Exception as exc:  # noqa: BLE001 — best-effort by contract
        logger.warning("summarize_chat(%s) failed: %s", chat_id, exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None


def _extract_topics(messages: list, max_topics: int = 5) -> list[str]:
    """Very light keyword extraction: frequent non-stopword user words."""
    try:
        stopwords = {
            "the", "a", "an", "and", "or", "but", "is", "are", "was", "were",
            "to", "of", "in", "on", "for", "with", "that", "this", "it", "as",
            "at", "by", "from", "be", "have", "has", "had", "do", "does",
            "i", "you", "we", "they", "my", "your", "can", "could", "would",
            "how", "what", "why", "when", "where", "who", "not", "no", "yes",
        }
        counts: dict[str, int] = {}
        for m in messages:
            if m.role != "user":
                continue
            for word in (m.content or "").lower().split():
                w = "".join(c for c in word if c.isalnum())
                if len(w) > 3 and w not in stopwords:
                    counts[w] = counts.get(w, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        return [w for w, _ in ranked[:max_topics]]
    except Exception:  # noqa: BLE001
        return []
