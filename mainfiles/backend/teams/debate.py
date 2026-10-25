"""
teams/debate.py — Capped persona debate (MiroFish substitute, NOT the
swarm).

MiroFish's whole product — OASIS + Zep Cloud social simulation with
per-agent-per-round LLM calls, thousands of agents — does NOT belong
in Sangam. What is portable is the small idea underneath it: personas
with persistent identity driving multi-round exchanges, then a
synthesis. This module is that idea, capped hard:

- personas stored like skill definitions (see ``teams.personas``);
- at most 8 personas, at most 6 rounds — more is refused, not trimmed
  silently (trimming would change whose voice is heard);
- transcript-fed fan-out: every persona sees the full transcript so
  far before speaking (no hidden state, no graph DB);
- coordinator synthesis at the end;
- a cost estimate BEFORE start (from a caller-supplied per-call
  estimate — the module never invents a price);
- a hard-stop button: any object with ``is_set()`` (e.g.
  ``threading.Event``), checked between speakers, never mid-call.

OASIS, Zep, social platforms, and 100-agent claims are out of scope
by design and are not implemented here.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

MAX_PERSONAS = 8
MAX_ROUNDS = 6

Completer = Callable[[list[dict[str, str]]], Awaitable[str]]


@dataclass
class DebateEstimate:
    personas: int
    rounds: int
    estimated_calls: int
    estimated_cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return {"personas": self.personas, "rounds": self.rounds,
                "estimated_calls": self.estimated_calls,
                "estimated_cost_usd": round(self.estimated_cost_usd, 4)}


def estimate_debate_cost(persona_count: int, rounds: int,
                         cost_per_call_usd: float = 0.0) -> DebateEstimate:
    """Cost estimate BEFORE start. Calls = personas x rounds (fan-out)
    + 1 coordinator synthesis. A zero per-call cost yields a zero
    estimate — the caller supplies the real figure; this module never
    invents one (cf. the old flat $0.01/1K fake meter)."""
    if persona_count < 1 or persona_count > MAX_PERSONAS:
        raise ValueError(f"persona count must be 1..{MAX_PERSONAS}")
    if rounds < 1 or rounds > MAX_ROUNDS:
        raise ValueError(f"rounds must be 1..{MAX_ROUNDS}")
    calls = persona_count * rounds + 1
    return DebateEstimate(personas=persona_count, rounds=rounds,
                          estimated_calls=calls,
                          estimated_cost_usd=calls * max(cost_per_call_usd, 0.0))


@dataclass
class DebateResult:
    topic: str
    transcript: list[dict[str, Any]] = field(default_factory=list)
    synthesis: str = ""
    stopped: bool = False
    stop_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"topic": self.topic, "transcript": self.transcript,
                "synthesis": self.synthesis, "stopped": self.stopped,
                "stop_reason": self.stop_reason}


MAX_SCENARIO_VARIABLES = 3


def position_ledger(transcript: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-persona position ledger (MiroFish portable idea, capped).

    A persona's stated positions are carried as a compact ledger so a
    later round cannot silently contradict an earlier one: each entry
    lists every round's statement plus the latest one, side by side.
    This module does NOT judge contradiction — "these two statements
    conflict" is a human/model judgment, and flagging it by keyword
    overlap would invent disagreements. The ledger surfaces the
    statements; the reader (or the closing report) judges."""
    ledger: dict[str, Any] = {}
    for turn in transcript or []:
        persona = str(turn.get("persona", "?"))
        entry = ledger.setdefault(persona, {"statements": [], "rounds_spoken": 0})
        entry["statements"].append({"round": turn.get("round"),
                                    "content": turn.get("content", "")})
        entry["rounds_spoken"] += 1
    for entry in ledger.values():
        entry["latest"] = entry["statements"][-1]["content"] if entry["statements"] else ""
    return ledger


def scenario_branches(topic: str, variables: list[str]) -> list[dict[str, Any]]:
    """Scenario branching: the same capped debate under 1-3 explicitly
    injected variables, so the user can see what flips the synthesis.

    Returns [{variable, topic}] where topic is the original topic plus
    the injected variable, stated as an assumption — never a hidden
    change to the question. Over-cap (0 or >3) is refused, not trimmed."""
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("Empty topic.")
    variables = [v.strip() for v in (variables or []) if v and v.strip()]
    if not variables or len(variables) > MAX_SCENARIO_VARIABLES:
        raise ValueError(
            f"Scenario variables must be 1..{MAX_SCENARIO_VARIABLES}, got {len(variables)}")
    return [{"variable": v,
             "topic": f"{topic} [scenario assumption: {v}]"} for v in variables]


def closing_report(topic: str, synthesis: str,
                   transcript: list[dict[str, Any]]) -> dict[str, Any]:
    """ReportAgent-style closing report tied to the debate transcript.

    {topic, synthesis, positions (the ledger), disagreements (lines
    where a persona explicitly disagrees — quoted, not inferred),
    assumptions, what_would_change_it}. ``what_would_change_it`` is
    deliberately plain: it names the disagreements that would have to
    resolve for the synthesis to change, and says so when the
    transcript shows none — it never invents a decisive factor."""
    ledger = position_ledger(transcript)
    disagreements = []
    for turn in transcript or []:
        content = turn.get("content", "") or ""
        if "disagree" in content.lower():
            disagreements.append({"persona": turn.get("persona"),
                                  "round": turn.get("round"),
                                  "quote": content.strip()[:300]})
    if disagreements:
        what_changes = ("Resolve these stated disagreements and the "
                        "synthesis would have to change: " +
                        "; ".join(f"{d['persona']} (round {d['round']})"
                                  for d in disagreements))
    else:
        what_changes = ("No explicit disagreement was stated in the "
                        "transcript, so nothing in the transcript itself "
                        "identifies what would change the synthesis.")
    return {"topic": topic, "synthesis": synthesis, "positions": ledger,
            "disagreements": disagreements,
            "assumptions": ["Every persona saw the full transcript before speaking.",
                            "No hidden state: the transcript is the whole debate."],
            "what_would_change_it": what_changes}


async def run_debate(topic: str, personas: list[Any], rounds: int,
                     completer: Completer, coordinator_prompt: str,
                     cost_per_call_usd: float = 0.0,
                     stop_flag: Any | None = None) -> DebateResult:
    """Run a capped debate. ``personas`` are Persona-like objects with
    ``slug``/``name`` and ``system_prompt``. The estimate is computed
    first (and returned implicitly via the caps check) — callers that
    need to show it should call ``estimate_debate_cost`` before this.
    Refuses over-cap requests outright; never silently trims."""
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("Empty topic.")
    estimate_debate_cost(len(personas), rounds, cost_per_call_usd)
    result = DebateResult(topic=topic)
    stop = stop_flag if stop_flag is not None else threading.Event()

    def transcript_text() -> str:
        return "\n\n".join(
            f"[{t['persona']}] {t['content']}" for t in result.transcript)

    for round_no in range(1, rounds + 1):
        for persona in personas:
            if stop.is_set():
                result.stopped = True
                result.stop_reason = "stopped"
                return result
            system = getattr(persona, "system_prompt", "") or (
                f"You are {getattr(persona, 'name', persona)}.")
            content = await completer([
                {"role": "system", "content": system},
                {"role": "user", "content": (
                    f"Debate topic: {topic}\n\nTranscript so far:\n"
                    f"{transcript_text() or '(nothing yet)'}\n\n"
                    f"Round {round_no}: respond in character, engaging what others said.")},
            ])
            result.transcript.append({"round": round_no,
                                      "persona": getattr(persona, "slug", str(persona)),
                                      "content": content or ""})
    if stop.is_set():
        result.stopped = True
        result.stop_reason = "stopped"
        return result
    result.synthesis = await completer([
        {"role": "system", "content": coordinator_prompt},
        {"role": "user", "content": (
            f"Debate topic: {topic}\n\nTranscript:\n{transcript_text()}\n\n"
            "Synthesize: where the personas agree, where they genuinely "
            "disagree, and what remains unresolved. Do not manufacture a "
            "consensus the transcript does not show.")},
    ])
    return result
