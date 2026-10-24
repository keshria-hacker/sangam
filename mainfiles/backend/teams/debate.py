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
