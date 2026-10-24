"""
reflection.py — Wave-2 deep-knowledge: evidence-backed reflections
(Hindsight port, algorithms only).

The key discipline change: reflect is READ-ONLY. Earlier code stored
its synthesis as a semantic memory, polluting future recall with a
second-hand summary. Nothing in this module writes to any store:
``reflect_read_only`` parses model output against recalled ids and
returns observations + evidence + a computed trend, and the caller
decides what (if anything) to display. This module deliberately
imports no memory store.

Also here: triage-first background consolidation planning. Triage is
cheap and deterministic (exact-text + near-duplicate similarity +
chatter heuristics); only records classified "changes" need an LLM
rewrite, which this planner leaves to the caller. ``apply_plan``
applies a prepared batch with a liveness re-check before every
write — ChromaDB has no multi-record transaction, so prepare-then-
recheck is the faithful equivalent of Hindsight's one-transaction
apply, and it is stated as such instead of claimed as atomic.
"""
from __future__ import annotations

import difflib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

TREND_STATES = ("new", "strengthening", "stable", "weakening", "stale")

_CHATTER_RES = re.compile(r"^(ok|okay|thanks|thank you|got it|noted|sure|yes|no|hmm|lol)\W*$", re.IGNORECASE)

NEAR_DUP_RATIO = 0.85


def parse_reflection(raw: str | None, valid_ids: set[str]) -> dict | None:
    """Parse reflect JSON; evidence ids are filtered to recalled ids.
    Returns None when the output is unparseable (caller answers 503
    and stores nothing — same contract as the endpoint's parser)."""
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(raw[start:end + 1])
        except (ValueError, TypeError):
            return None
    if not isinstance(data, dict):
        return None
    observations = []
    if isinstance(data.get("observations"), list):
        for item in data["observations"][:20]:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                evidence = [e for e in item.get("evidence", [])
                            if isinstance(e, str) and e in valid_ids]
                observations.append({"text": item["text"].strip(), "evidence": evidence})
    mental_model = data.get("mental_model") if isinstance(data.get("mental_model"), str) else ""
    questions = [q.strip() for q in data.get("open_questions", [])
                 if isinstance(q, str) and q.strip()][:20]
    if not observations and not mental_model.strip() and not questions:
        return None
    return {"observations": observations, "mental_model": mental_model.strip(),
            "open_questions": questions}


def compute_trend(
    evidence_dates: list[datetime], now: datetime | None = None,
) -> str:
    """Five-state trend over 30/90-day windows (Hindsight shape):

    * stale — no evidence in the last 90 days (or none at all)
    * new — evidence in the last 90 days but none in the prior 60
    * strengthening/stable/weakening — compare the last-30-day rate
      against the prior-60-day rate (prior count scaled to 30 days);
      within +/-25% counts as stable.
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    normed = []
    for d in evidence_dates or []:
        if d.tzinfo is None:
            d = d.replace(tzinfo=UTC)
        normed.append(d)
    last90 = [d for d in normed if now - timedelta(days=90) <= d <= now]
    if not last90:
        return "stale"
    last30 = [d for d in last90 if now - timedelta(days=30) <= d <= now]
    prior = len(last90) - len(last30)
    if prior == 0:
        return "new"
    prior_rate_30d = prior * (30.0 / 60.0)
    if not last30:
        return "weakening"
    ratio = len(last30) / prior_rate_30d if prior_rate_30d else float("inf")
    if ratio >= 1.25:
        return "strengthening"
    if ratio <= 0.75:
        return "weakening"
    return "stable"


def reflect_read_only(
    records: list[dict[str, Any]], raw_model_output: str | None,
    now: datetime | None = None,
) -> dict | None:
    """Build an evidence-backed reflection WITHOUT writing anything.

    ``records`` are recalled memories as dicts with at least ``id``
    and ``created_at`` (datetime or ISO string). Returns None when
    the model output is unparseable. The result carries
    ``stored: False`` explicitly so no caller mistakes it for a
    persisted memory."""
    valid_ids = {str(r["id"]) for r in records if r.get("id")}
    parsed = parse_reflection(raw_model_output, valid_ids)
    if parsed is None:
        return None
    evidence_ids = sorted({e for o in parsed["observations"] for e in o["evidence"]})
    dates: list[datetime] = []
    by_id = {str(r["id"]): r for r in records}
    for eid in evidence_ids:
        created = by_id.get(eid, {}).get("created_at")
        if isinstance(created, datetime):
            dates.append(created)
        elif isinstance(created, str):
            try:
                dates.append(datetime.fromisoformat(created.replace("Z", "+00:00")))
            except ValueError:
                pass
    return {
        "observations": parsed["observations"],
        "mental_model": parsed["mental_model"],
        "open_questions": parsed["open_questions"],
        "evidence_ids": evidence_ids,
        "proof_count": len(evidence_ids),
        "trend": compute_trend(dates, now=now),
        "stored": False,
    }


def triage_new(text: str, existing: list[dict[str, Any]]) -> str:
    """Classify one candidate memory against existing records:
    ``chatter`` (generic acknowledgement), ``restates`` (exact or
    near-duplicate of an existing record), ``changes`` (shares a
    long token overlap but differs — needs an LLM rewrite decision),
    or ``new``. Pure heuristic; the caller decides the write."""
    stripped = (text or "").strip()
    if not stripped:
        return "chatter"
    if _CHATTER_RES.match(stripped) or len(stripped) < 12:
        return "chatter"
    for rec in existing:
        content = (rec.get("content") or "").strip()
        if not content:
            continue
        if content == stripped:
            return "restates"
        if difflib.SequenceMatcher(None, content, stripped).ratio() >= NEAR_DUP_RATIO:
            return "restates"
    # "Changes": shares most content words with an existing record
    # but is not a near-duplicate — a candidate update, not a create.
    new_tokens = set(re.findall(r"[a-z0-9]+", stripped.lower()))
    for rec in existing:
        old_tokens = set(re.findall(r"[a-z0-9]+", (rec.get("content") or "").lower()))
        if old_tokens and new_tokens and len(new_tokens & old_tokens) / len(new_tokens | old_tokens) >= 0.5:
            return "changes"
    return "new"


def plan_consolidation(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Triage-first consolidation plan over existing records.

    Batched actions, prepared before any write:
    * exact-text duplicates (keep earliest) -> DELETE the rest
    * near-duplicates (ratio >= 0.85, keep earliest, longer text wins)
      -> UPDATE the kept record, DELETE the rest
    * chatter records -> DELETE
    Everything else -> keep. ``decisions`` records the verdict per
    record id so the batch is auditable. No writes happen here.
    """
    plan: dict[str, Any] = {"create": [], "update": [], "delete": [],
                            "decisions": []}
    seen_exact: dict[str, dict[str, Any]] = {}
    kept: list[dict[str, Any]] = []
    for rec in sorted(records, key=lambda r: str(r.get("created_at") or "")):
        content = (rec.get("content") or "").strip()
        rid = str(rec.get("id"))
        if not content:
            plan["delete"].append(rid)
            plan["decisions"].append({"id": rid, "verdict": "chatter"})
            continue
        if content in seen_exact:
            plan["delete"].append(rid)
            plan["decisions"].append(
                {"id": rid, "verdict": "restates", "kept_id": str(seen_exact[content].get("id"))})
            continue
        if _CHATTER_RES.match(content):
            plan["delete"].append(rid)
            plan["decisions"].append({"id": rid, "verdict": "chatter"})
            continue
        merged_into = None
        for kept_rec in kept:
            kept_content = (kept_rec.get("content") or "").strip()
            if difflib.SequenceMatcher(None, kept_content, content).ratio() >= NEAR_DUP_RATIO:
                merged_into = kept_rec
                break
        if merged_into is not None:
            kept_content = (merged_into.get("content") or "").strip()
            winner = content if len(content) > len(kept_content) else kept_content
            plan["update"].append({"id": str(merged_into.get("id")), "content": winner})
            plan["delete"].append(rid)
            plan["decisions"].append(
                {"id": rid, "verdict": "restates", "kept_id": str(merged_into.get("id"))})
            continue
        seen_exact[content] = rec
        kept.append(rec)
        plan["decisions"].append({"id": rid, "verdict": "new"})
    return plan


def apply_plan(
    plan: dict[str, Any],
    get_record: Callable[[str], Any],
    delete_fn: Callable[[str], bool],
    update_fn: Callable[[str, str], bool],
) -> dict[str, int]:
    """Apply a prepared plan with a liveness re-check before every
    write: a record deleted or changed since planning is skipped,
    never blindly overwritten. Returns applied/skipped counts per
    action kind. Not a DB transaction (ChromaDB has none) — the
    re-check is what keeps a stale plan from corrupting live data."""
    result = {"updated": 0, "deleted": 0, "skipped": 0}
    for upd in plan.get("update", []):
        if get_record(upd["id"]) is None:
            result["skipped"] += 1
            continue
        if update_fn(upd["id"], upd["content"]):
            result["updated"] += 1
        else:
            result["skipped"] += 1
    for rid in plan.get("delete", []):
        if get_record(rid) is None:
            result["skipped"] += 1
            continue
        if delete_fn(rid):
            result["deleted"] += 1
        else:
            result["skipped"] += 1
    return result
