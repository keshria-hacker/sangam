"""
memory/extract_llm.py — Batch 4: LLM fact extraction (mem0-style).

On-demand only: this module is called from POST /api/memory/extract and
POST /api/memory/entities/extract. It is deliberately NOT wired into the
chat loop — heuristic auto-extraction (memory/extract.py) stays the
chat-loop path, so a bad model response can never corrupt live chat.

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

import json
import logging
import re
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
