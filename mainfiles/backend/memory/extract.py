"""
memory/extract.py — automatic memory extraction from conversation turns.

Offline heuristics (no LLM): scans the user's message for sentences that
carry durable information (facts, preferences, corrections, procedures),
scores them, dedupes against existing memories, and stores the survivors.
Conservative: at most a few memories per turn, duplicates bump importance
instead of creating new records. Never raises.
"""
from __future__ import annotations

import asyncio
import logging

from .models import MemoryRecord
from .retrieval import find_near_duplicate
from .scoring import score_importance, split_sentences
from .store import save_memory, update_importance

logger = logging.getLogger(__name__)

MAX_PER_TURN = 2
MIN_IMPORTANCE_TO_STORE = 0.55


async def extract_from_turn(
    user_text: str,
    chat_id: str = "",
    user_id: str = "",
) -> list[MemoryRecord]:
    """Extract and store candidate memories from one user turn."""
    saved: list[MemoryRecord] = []
    try:
        for sentence in split_sentences(user_text):
            if len(saved) >= MAX_PER_TURN:
                break
            importance, kind = score_importance(sentence)
            if importance < MIN_IMPORTANCE_TO_STORE:
                continue
            # Dedupe: a near-duplicate just gets more important.
            existing = await find_near_duplicate(sentence, user_id=user_id)
            if existing is not None:
                await update_importance(
                    existing.id, min(1.0, existing.importance + 0.05)
                )
                continue
            record = await save_memory(
                sentence,
                kind=kind,
                chat_id=chat_id,
                user_id=user_id,
                importance=importance,
            )
            if record is not None:
                saved.append(record)
    except Exception as exc:  # noqa: BLE001
        logger.warning("extract_from_turn failed: %s", exc)
    return saved


def extract_from_turn_background(
    user_text: str, chat_id: str = "", user_id: str = ""
) -> None:
    """Fire-and-forget wrapper for the chat pipeline (never blocks streaming)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(extract_from_turn(user_text, chat_id=chat_id, user_id=user_id))
