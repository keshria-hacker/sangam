"""
memory/extract_llm.py — Batch 4: LLM fact extraction (mem0-style).

Two callers: (1) on-demand POST /api/memory/extract and
POST /api/memory/entities/extract (``extract_facts_llm``), and
(2) deep-memory chat wiring (``extract_chat_memories_llm``): a
background, post-response step in the chat loop, gated by the same
``memoryAutoExtract`` setting as heuristic auto-extraction
(memory/extract.py). The chat path never blocks on the model, and a
bad model response can never corrupt live chat: unparseable output
yields empty results, and the heuristic path stays the no-model
fallback.

Honesty contract:
- No configured model -> no facts, no entities, no relations. The
  caller reports ``model_used: false``; nothing is invented.
- Unparseable model output -> empty results, never invented facts.
  The raw output is never stored as a "fact".
- Saved facts go through the existing store as SEMANTIC memories, so
  they behave exactly like any other memory (recall, decay, export).

``complete_text`` is the single seam tests patch: it resolves the
configured default model and collects one streamed completion into a
string, or returns None when no model is configured. Route modules
call it as ``extract_llm.complete_text(...)`` so a monkeypatch on this
module attribute takes effect everywhere.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM = (
    "Extract durable facts about the user from the text below. "
    "Return ONLY a JSON object with exactly these keys: "
    '"facts": [strings, each one self-contained durable fact], '
    '"entities": [{"name": string, "kind": string}] where kind is one of '
    'person, place, project, topic, tool, organization, other, and '
    '"relations": [{"subject": string, "predicate": string, "object": string}] '
    "for current attributes (e.g. subject=user, predicate=prefers, object=concise answers). "
    "Do not invent facts, entities, or relations that are not in the text. "
    "If there is nothing durable, return empty arrays."
)

# Sentence-initial words that are not entities on their own.
_CAPITALIZED_STOP = {
    "The", "A", "An", "I", "It", "This", "That", "These", "Those",
    "He", "She", "We", "You", "They", "My", "His", "Her", "Our",
    "In", "On", "At", "For", "With", "From", "To", "And", "But", "Or",
}

_CAPITALIZED_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")


def extract_capitalized_entities(text: str) -> list[str]:
    """Heuristic fallback: multi-word Capitalized phrases only.

    Single capitalized words are mostly sentence starts, so they are
    excluded — this keeps the fallback conservative and clearly
    labelled as heuristic, never presented as LLM output.
    """
    found: list[str] = []
    for match in _CAPITALIZED_RE.finditer(text or ""):
        phrase = " ".join(match.group(1).split())
        words = phrase.split(" ")
        if words[0] in _CAPITALIZED_STOP and len(words) <= 2:
            continue
        if phrase not in found:
            found.append(phrase)
    return found[:50]


def parse_extraction(raw: str | None) -> dict[str, list]:
    """Defensively parse model JSON into facts/entities/relations.

    Tries strict JSON, then the largest ``{...}`` span. Anything else
    -> empty lists. Values are validated to strings; malformed entries
    are dropped, never repaired by guessing.
    """
    empty: dict[str, list] = {"facts": [], "entities": [], "relations": []}
    if not raw or not raw.strip():
        return empty
    data: Any = None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start:end + 1])
            except (ValueError, TypeError):
                return empty
        else:
            return empty
    if not isinstance(data, dict):
        return empty

    def _strings(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [s.strip() for s in value if isinstance(s, str) and s.strip()][:20]

    facts = _strings(data.get("facts"))

    entities: list[dict[str, str]] = []
    if isinstance(data.get("entities"), list):
        for item in data["entities"][:50]:
            if isinstance(item, dict) and item.get("name") and isinstance(item["name"], str):
                entities.append({
                    "name": item["name"].strip()[:200],
                    "kind": item["kind"].strip()[:64] if isinstance(item.get("kind"), str) and item["kind"].strip() else "other",
                })
            elif isinstance(item, str) and item.strip():
                entities.append({"name": item.strip()[:200], "kind": "other"})

    relations: list[dict[str, str]] = []
    if isinstance(data.get("relations"), list):
        for item in data["relations"][:50]:
            if isinstance(item, dict) and all(
                isinstance(item.get(k), str) and item[k].strip()
                for k in ("subject", "predicate", "object")
            ):
                relations.append({
                    "subject": item["subject"].strip()[:200],
                    "predicate": item["predicate"].strip()[:128],
                    "object": item["object"].strip()[:200],
                })
    return {"facts": facts, "entities": entities, "relations": relations}


async def complete_text(
    db: Any, messages: list[dict], max_tokens: int = 2000
) -> str | None:
    """One non-streaming completion from the configured default model.

    Returns None when no model is configured (callers turn this into
    503 / a ``model_used: false`` response, never fake content).
    Provider errors propagate so callers can also answer 503 honestly.
    """
    from ..llm import default_model_id, stream_completion

    model_id = await default_model_id(db)
    if not model_id:
        return None
    parts: list[str] = []
    async for chunk in stream_completion(
        model_id, messages, db, temperature=0.2, max_tokens=max_tokens
    ):
        text = chunk if isinstance(chunk, str) else getattr(chunk, "text", None)
        if text:
            parts.append(text)
    return "".join(parts).strip()


async def extract_facts_llm(
    text: str, db: Any, chat_id: str = "", user_id: str = ""
) -> dict[str, Any]:
    """Run LLM extraction over ``text`` and save facts as semantic memories.

    Returns the parsed facts/entities/relations, the saved memory
    records, and ``model_used``. Never raises: a failed model call or
    an unparseable response yields empty results (and no saved facts).
    """
    from .models import MemoryKind
    from .store import save_memory

    text = (text or "").strip()
    if not text:
        return {"facts": [], "entities": [], "relations": [],
                "saved": [], "model_used": False}
    try:
        raw = await complete_text(
            db,
            [
                {"role": "system", "content": EXTRACTION_SYSTEM},
                {"role": "user", "content": text},
            ],
        )
    except Exception as exc:  # noqa: BLE001 — extraction must never crash a request
        logger.warning("LLM extraction failed: %s", exc)
        return {"facts": [], "entities": [], "relations": [],
                "saved": [], "model_used": False, "error": str(exc)[:200]}
    if raw is None:
        return {"facts": [], "entities": [], "relations": [],
                "saved": [], "model_used": False}
    parsed = parse_extraction(raw)
    saved = []
    for fact in parsed["facts"]:
        record = await save_memory(
            fact, kind=MemoryKind.SEMANTIC, chat_id=chat_id, user_id=user_id,
            importance=0.7,
        )
        if record is not None:
            saved.append({"id": record.id, "content": record.content})
    return {**parsed, "saved": saved, "model_used": True}


# ---------------------------------------------------------------------------
# Deep-memory: mem0-style ADDITIVE extraction for the chat path
# ---------------------------------------------------------------------------
# The endpoint path above stays as-is. The chat path uses a different
# contract, ported from mem0's live ``_add_to_vector_store`` pipeline:
# last-10-messages context + top recalled memories (real ids remapped
# to small ints so the model can neither invent nor leak real ids),
# ONE additive call over BOTH roles (assistant content reframed as
# "User was recommended X" / "User's plan includes X"), relative time
# resolved against the conversation's observation date (never
# "today"), md5 dedup, and linked_memory_ids remapped back to real
# ids. Unparseable output -> empty, exactly like the endpoint path:
# never invent memories from output that does not parse.

ADDITIVE_EXTRACTION_SYSTEM = (
    "Extract durable facts about the user from the conversation below. "
    "Return ONLY a JSON object with exactly this key: "
    '"memory": [{"text": string, "attributed_to": "user" or "assistant", '
    '"linked_memory_ids": [small integer ids from Existing Memories]}]. '
    "Rules: extract from BOTH user and assistant messages — assistant "
    "content becomes facts about the user, e.g. 'User was recommended X' "
    "or 'User's plan includes X'. Do NOT re-extract anything already in "
    "Existing Memories; when a new fact extends one, list its small id "
    "in linked_memory_ids. Resolve ALL relative time against the "
    "Observation Date given (never today's date): 'last week' becomes a "
    "concrete date. Do not invent facts, people, or dates that are not "
    "in the conversation. If there is nothing durable, return "
    '{"memory": []}.'
)

CHAT_EXTRACTION_MAX_MESSAGES = 10
CHAT_EXTRACTION_MAX_RECALLED = 10


def _normalize_for_hash(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().casefold())


def md5_dedup_key(text: str) -> str:
    """mem0-style exact-text dedup key (normalized md5)."""
    return hashlib.md5(_normalize_for_hash(text).encode("utf-8")).hexdigest()


def _turns_from_messages(messages: list[Any]) -> list[dict[str, str]]:
    """Normalize dicts / pydantic messages to user/assistant turns."""
    turns: list[dict[str, str]] = []
    for m in messages or []:
        if isinstance(m, dict):
            role, content = m.get("role", ""), m.get("content", "")
        else:
            role, content = getattr(m, "role", ""), getattr(m, "content", "")
        if role not in ("user", "assistant"):
            continue
        content = content if isinstance(content, str) else ""
        if content.strip():
            turns.append({"role": role, "content": content.strip()})
    return turns[-CHAT_EXTRACTION_MAX_MESSAGES:]


def build_additive_prompt(
    messages: list[Any],
    existing_memories: list[Any],
    observation_date: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Build the additive extraction user prompt.

    Returns (prompt, id_map) where id_map maps the small-int strings
    shown to the model back to real memory ids. Existing memories are
    MemoryRecords or (id, text) pairs; at most 10 are shown.
    """
    turns = _turns_from_messages(messages)
    observation_date = observation_date or datetime.now(UTC).date().isoformat()
    id_map: dict[str, str] = {}
    lines: list[str] = [f"Observation Date: {observation_date}", "", "Existing Memories:"]
    for idx, item in enumerate(list(existing_memories or [])[:CHAT_EXTRACTION_MAX_RECALLED]):
        if isinstance(item, tuple):
            real_id, text = str(item[0]), str(item[1])
        else:
            real_id, text = str(getattr(item, "id", "")), str(getattr(item, "content", ""))
        if not real_id or not text.strip():
            continue
        small = str(len(id_map))
        id_map[small] = real_id
        lines.append(f"[{small}] {text.strip()}")
    if not id_map:
        lines.append("(none)")
    lines.append("")
    lines.append("Conversation (last 10 user/assistant turns):")
    for turn in turns:
        lines.append(f"{turn['role']}: {turn['content']}")
    return "\n".join(lines), id_map


def parse_additive_extraction(raw: str | None, id_map: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Parse additive extraction output into linked fact dicts.

    Unparseable input -> [] (never invented facts). linked_memory_ids
    are remapped through id_map; ids the model invents (not in the
    map and not a real id) are dropped, never stored. A fact with an
    empty text is dropped.
    """
    id_map = id_map or {}
    if not raw or not raw.strip():
        return []
    data: Any = None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start:end + 1])
            except (ValueError, TypeError):
                return []
        else:
            return []
    if not isinstance(data, dict) or not isinstance(data.get("memory"), list):
        return []
    facts: list[dict[str, Any]] = []
    for item in data["memory"][:20]:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        attributed = item.get("attributed_to")
        attributed = attributed if attributed in ("user", "assistant") else "user"
        linked: list[str] = []
        raw_links = item.get("linked_memory_ids")
        if isinstance(raw_links, list):
            for link in raw_links:
                key = str(link).strip()
                if key in id_map:
                    linked.append(id_map[key])
                elif key in set(id_map.values()):
                    linked.append(key)
                # Unknown ids are dropped: the model must not invent links.
        facts.append({
            "text": text.strip()[:2000],
            "attributed_to": attributed,
            "linked_memory_ids": linked,
        })
    return facts


async def extract_chat_memories_llm(
    messages: list[Any],
    assistant_text: str = "",
    chat_id: str = "",
    user_id: str = "",
    recalled: list[Any] | None = None,
    observation_date: str | None = None,
) -> dict[str, Any]:
    """Background LLM extraction for one chat turn (mem0-style additive).

    ``messages`` is the turn history (dicts or message objects);
    ``assistant_text`` is the just-streamed reply, appended as the
    final assistant turn so assistant recommendations and plans are
    extracted too — the heuristic path only ever sees user text.
    When ``recalled`` is None, top-10 memories are recalled for the
    last user turn first (no touch: extraction must not inflate
    access stats). Never raises: no model, a failed call, or
    unparseable output all yield empty results and ``model_used``
    False (no model) or True with no saves (bad output).
    Returns {"saved": [...], "model_used": bool, "facts": [...]}.
    """
    from .models import MemoryKind
    from .retrieval import find_near_duplicate, recall
    from .store import save_memory

    turns_source = list(messages or [])
    if assistant_text and str(assistant_text).strip():
        turns_source = [*turns_source, {"role": "assistant", "content": str(assistant_text)}]
    turns = _turns_from_messages(turns_source)
    if not turns:
        return {"facts": [], "saved": [], "model_used": False}
    if recalled is None:
        last_user = next((t["content"] for t in reversed(turns) if t["role"] == "user"), "")
        try:
            recalled = await recall(last_user, top_k=CHAT_EXTRACTION_MAX_RECALLED, touch=False) if last_user else []
        except Exception as exc:  # noqa: BLE001 — recall must not kill extraction
            logger.warning("chat extraction recall failed: %s", exc)
            recalled = []
    prompt, id_map = build_additive_prompt(turns_source, recalled or [], observation_date)
    try:
        from ..database import AsyncSessionLocal

        async with AsyncSessionLocal() as bg_db:
            raw = await complete_text(
                bg_db,
                [
                    {"role": "system", "content": ADDITIVE_EXTRACTION_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            )
    except Exception as exc:  # noqa: BLE001 — extraction must never crash chat
        logger.warning("chat LLM extraction failed: %s", exc)
        return {"facts": [], "saved": [], "model_used": False, "error": str(exc)[:200]}
    if raw is None:
        # No model configured: heuristic extraction (already run by the
        # caller) stays the fallback; nothing is invented here.
        return {"facts": [], "saved": [], "model_used": False}
    facts = parse_additive_extraction(raw, id_map)
    seen_hashes = {md5_dedup_key(getattr(r, "content", "") if not isinstance(r, tuple) else r[1])
                   for r in (recalled or [])}
    saved: list[dict[str, Any]] = []
    for fact in facts:
        key = md5_dedup_key(fact["text"])
        if key in seen_hashes:
            continue  # exact-text dedup against existing + this batch
        seen_hashes.add(key)
        # Near-duplicate (e.g. the heuristic path just saved the same
        # sentence concurrently) bumps importance instead of doubling.
        try:
            existing = await find_near_duplicate(fact["text"], user_id=user_id)
        except Exception:  # noqa: BLE001
            existing = None
        if existing is not None:
            from .store import update_importance

            await update_importance(existing.id, min(1.0, existing.importance + 0.05))
            continue
        record = await save_memory(
            fact["text"], kind=MemoryKind.SEMANTIC, chat_id=chat_id,
            user_id=user_id, importance=0.7,
            linked_memory_ids=fact["linked_memory_ids"],
        )
        if record is not None:
            saved.append({
                "id": record.id, "content": record.content,
                "linked_memory_ids": record.linked_memory_ids,
                "attributed_to": fact["attributed_to"],
            })
    return {"facts": facts, "saved": saved, "model_used": True}
