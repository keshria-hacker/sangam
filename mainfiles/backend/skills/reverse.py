"""skills/reverse.py — propose skills from transcripts and runs (Batch 10).

reverse-skill mechanism, Sangam-native (the upstream reverse-skill
repo was absent from the deep-read clones, so nothing is claimed from
it — this is the mechanism the name implies, built on Sangam's own
creator + Runs data):

* :func:`propose_skill_from_transcript` — deterministic extraction
  from a chat transcript: the user's repeated requests become the
  draft's triggers, the most frequent content words become tags, and
  the draft body is a template the USER edits before saving. Nothing
  is saved here — saving is a separate, user-reviewed step via
  ``creator.draft_skill`` (route: ``POST /skills/drafts/save``).
* :func:`propose_skills_from_runs` — the scientific-agent-skills
  autoskill loop, minus screen capture (Sangam has no screenpipe and
  must not invent one): cluster the user's OWN run history (Runs
  centre titles) by shared words and stage one draft per cluster.
  User-triggered only, human approval before publish — never
  automatic, never from captured screen content.

Both functions are deterministic (no model call), so drafts are
inspectable and testable. A draft is a proposal, not a skill: it has
no effect until the user reviews and saves it.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

_STOPWORDS = {"the", "and", "for", "with", "this", "that", "from", "into",
              "your", "you", "are", "was", "were", "have", "has", "will",
              "about", "after", "before", "when", "what", "which", "then",
              "please", "just", "like", "also", "than", "them", "they",
              "can", "could", "should", "would", "there", "here", "how",
              "why", "not", "but", "all", "any", "per", "via", "use",
              "using", "used", "make", "made", "get", "got", "let", "one",
              "two", "new", "add", "need", "want", "help", "show", "give"}

_WORD = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")


def _content_words(text: str) -> list[str]:
    return [w for w in _WORD.findall((text or "").lower())
            if w not in _STOPWORDS]


def _user_turns(transcript: list[dict] | str) -> list[str]:
    if isinstance(transcript, str):
        return [transcript]
    turns = []
    for turn in transcript or []:
        if isinstance(turn, dict) and turn.get("role") in ("user", None):
            content = str(turn.get("content", "")).strip()
            if content:
                turns.append(content)
        elif isinstance(turn, str) and turn.strip():
            turns.append(turn.strip())
    return turns


def propose_skill_from_transcript(transcript: list[dict] | str,
                                  name_hint: str | None = None) -> dict:
    """Draft a skill proposal from a chat transcript (user review required).

    Returns {name, description, triggers, tags, body, evidence}.
    Raises ValueError when the transcript has no usable user content —
    an empty draft is never produced.
    """
    turns = _user_turns(transcript)
    if not turns:
        raise ValueError("transcript has no user turns to learn a skill from")
    counts = Counter()
    for turn in turns:
        counts.update(set(_content_words(turn)))
    top = [w for w, _ in counts.most_common(8)]
    if not top:
        raise ValueError("transcript has no content words to learn a skill from")
    # Triggers: short repeated user phrases (2-4 words) + top words.
    phrases: Counter = Counter()
    for turn in turns:
        words = _content_words(turn)
        for size in (2, 3):
            for i in range(len(words) - size + 1):
                phrases[" ".join(words[i:i + size])] += 1
    triggers = [p for p, c in phrases.most_common(5) if c >= 2]
    triggers += [w for w in top[:3] if w not in triggers]
    name = (name_hint or "-".join(top[:2]) or "learned-skill").strip().lower()
    name = re.sub(r"[^a-z0-9-]+", "-", name).strip("-") or "learned-skill"
    first = turns[0][:200]
    body = (
        f"# {name}\n\n"
        "Draft proposed from a conversation — REVIEW BEFORE SAVING.\n"
        "Edit the steps below so they describe the procedure exactly;\n"
        "delete anything the conversation did not actually show.\n\n"
        "## When to use\n\n"
        f"When the user asks for something like: {first}\n\n"
        "## Procedure\n\n"
        "1. Restate the goal in one sentence and confirm it.\n"
        "2. Follow the steps the conversation demonstrated.\n"
        "3. Verify the result before reporting it done.\n"
    )
    return {"name": name,
            "description": f"Learned from conversation: {first[:120]}",
            "triggers": triggers[:6], "tags": top[:6], "body": body,
            "evidence": {"user_turns": len(turns),
                         "repeated_phrases": triggers,
                         "source": "chat transcript (user turns only)"},
            "status": "draft — user review required before saving"}


def propose_skills_from_runs(runs: list[dict], min_cluster: int = 2) -> list[dict]:
    """Stage skill drafts from the user's own run history (Runs data only).

    Clusters run titles by their most common shared content word;
    clusters with fewer than ``min_cluster`` runs are dropped (a single
    run is not a repeatable workflow). Returns draft dicts in the same
    shape as :func:`propose_skill_from_transcript`.
    """
    by_word: dict[str, list[dict]] = {}
    for run in runs or []:
        title = str((run or {}).get("title", "") or (run or {}).get("kind", ""))
        for word in set(_content_words(title)):
            by_word.setdefault(word, []).append(run)
    drafts: list[dict] = []
    used: set[str] = set()
    for word, cluster in sorted(by_word.items(), key=lambda kv: -len(kv[1])):
        if len(cluster) < min_cluster:
            continue
        ids = [str(r.get("id", "")) for r in cluster if r.get("id")]
        if any(i in used for i in ids):
            continue
        used.update(ids)
        titles = "; ".join(str(r.get("title", "")) for r in cluster[:3])
        drafts.append({
            "name": f"{word}-workflow",
            "description": f"Repeated workflow seen in {len(cluster)} runs: {titles[:150]}",
            "triggers": [word], "tags": [word],
            "body": (f"# {word}-workflow\n\nDraft proposed from run history — "
                     "REVIEW BEFORE SAVING.\n\n## When to use\n\n"
                     f"When the work resembles these runs: {titles}\n\n"
                     "## Procedure\n\n1. Restate the goal and confirm it.\n"
                     "2. Follow the demonstrated steps.\n"
                     "3. Verify before reporting done.\n"),
            "evidence": {"runs": len(cluster), "run_ids": ids,
                         "source": "Runs centre titles (no screen capture)"},
            "status": "draft — user review required before saving"})
    return drafts
