"""
backend.memory — MemPalace-inspired cross-session memory.

Public surface (all never-raise by contract):
- recall(query, ...) -> ranked list[MemoryRecord]
- save_memory / get_memory / delete_memory / list_memories
- extract_from_turn_background(...) — auto-extract after a chat turn
- consolidate(...) — decay + prune pass
- Legacy: store_memory, retrieve_memories, reset_memory_for_testing,
  COLLECTION_NAME (kept for summarizer.py and older tests)
"""
from __future__ import annotations

from .consolidation import consolidate
from .extract import (
    extract_from_turn,
    extract_from_turn_background,
    extract_from_turn_llm_background,
)
from .extract_llm import (
    build_additive_prompt,
    extract_chat_memories_llm,
    parse_additive_extraction,
)
from .models import MemoryKind, MemoryRecord
from .retrieval import entity_boosts, find_near_duplicate, graph_entity_names, recall, retrieve_memories
from .scoring import rank_score
from .store import (
    COLLECTION_NAME,
    delete_memory,
    get_memory,
    list_memories,
    memory_stats,
    reset_memory_for_testing,
    save_memory,
    store_memory,
    touch_memory,
    update_importance,
)


def register_memory_extension() -> bool:
    """Project memory++ into the unified extension registry (best-effort)."""
    try:
        from ..extensions import ExtensionKind, ExtensionManifest, extensions
    except ImportError:
        return False
    extensions.register(
        ExtensionManifest(
            name="capability:memory",
            version="2.0.0",
            kind=ExtensionKind.CAPABILITY,
            description=(
                "Long-term memory: typed records (episodic/semantic/procedural), "
                "importance-ranked recall, auto-extraction, consolidation."
            ),
            enabled_by_default=True,
        )
    )
    return True


__all__ = [
    "COLLECTION_NAME",
    "MemoryKind",
    "MemoryRecord",
    "build_additive_prompt",
    "consolidate",
    "delete_memory",
    "entity_boosts",
    "extract_chat_memories_llm",
    "extract_from_turn",
    "extract_from_turn_background",
    "extract_from_turn_llm_background",
    "graph_entity_names",
    "parse_additive_extraction",
    "find_near_duplicate",
    "get_memory",
    "list_memories",
    "memory_stats",
    "rank_score",
    "recall",
    "register_memory_extension",
    "reset_memory_for_testing",
    "retrieve_memories",
    "save_memory",
    "store_memory",
    "touch_memory",
    "update_importance",
]
