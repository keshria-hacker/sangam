"""
teams/threads.py — Resumable team threads (Teams v2).

Wave-1's teams were one-shot fan-out: a paused team could not resume
mid-thread. A thread here is a persisted, append-only entry log
(one JSON object per line) under a thread directory, so a run that
stops — on a bound, on disagreement, or on interruption — resumes
exactly where it stopped: every transition is derived from the
persisted entries, and nothing auto-resumes after a process restart
(the caller re-enters explicitly via ``resume_thread``).

Bounds (Dodaios-style, Sangam-shaped): members, rounds, wall-clock
time, and estimated cost. Hitting a bound stops the thread with a
typed reason + open points and waits for the person — it never
silently truncates or auto-continues.

The runner takes a ``completer`` callable (``async (messages) ->
str``) so tests run it with a fake and production passes the LLM
stream collector; this module never imports the LLM layer.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

MAX_MEMBERS = 8
MAX_ROUNDS = 10


@dataclass
class ThreadBounds:
    max_members: int = MAX_MEMBERS
    max_rounds: int = MAX_ROUNDS
    max_seconds: float = 600.0
    max_cost_usd: float = 5.0

    def validate(self) -> None:
        if not (2 <= self.max_members <= MAX_MEMBERS):
            raise ValueError(f"max_members must be 2..{MAX_MEMBERS}")
        if not (1 <= self.max_rounds <= MAX_ROUNDS):
            raise ValueError(f"max_rounds must be 1..{MAX_ROUNDS}")
        if self.max_seconds <= 0 or self.max_cost_usd < 0:
            raise ValueError("max_seconds must be > 0 and max_cost_usd >= 0")


@dataclass
class ThreadEntry:
    kind: str  # "member" | "coordinator" | "bound" | "note"
    agent_id: str
    content: str
    round_no: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "agent_id": self.agent_id, "content": self.content,
                "round_no": self.round_no, "cost_usd": self.cost_usd}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThreadEntry":
        return cls(kind=data.get("kind", "note"), agent_id=data.get("agent_id", ""),
                   content=data.get("content", ""), round_no=int(data.get("round_no", 0)),
                   cost_usd=float(data.get("cost_usd", 0.0)))


class TeamThread:
    """One persisted thread. ``entries`` is the source of truth; the
    JSONL file is written on every append (atomic append via a single
    open-append per call is enough for single-process use)."""

    def __init__(self, thread_id: str, directory: str | Path, task: str,
                 member_ids: list[str], bounds: ThreadBounds | None = None):
        bounds = bounds or ThreadBounds()
        bounds.validate()
        if len(member_ids) > bounds.max_members:
            raise ValueError(f"{len(member_ids)} members exceeds max_members={bounds.max_members}")
        self.thread_id = thread_id
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.task = task
        self.member_ids = list(member_ids)
        self.bounds = bounds
        self.entries: list[ThreadEntry] = []
        self.started_at = time.monotonic()
        self._load()

    @property
    def path(self) -> Path:
        return self.directory / "entries.jsonl"

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                self.entries.append(ThreadEntry.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError, ValueError, KeyError):
                continue

    def append(self, entry: ThreadEntry) -> None:
        self.entries.append(entry)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.to_dict()) + "\n")

    @property
    def rounds_done(self) -> int:
        return max((e.round_no for e in self.entries), default=0)

    @property
    def cost_usd(self) -> float:
        return sum(e.cost_usd for e in self.entries)

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at

    def bound_hit(self) -> str | None:
        """Typed bound reason, or None when the thread may continue."""
        if self.rounds_done >= self.bounds.max_rounds:
            return "rounds"
        if self.elapsed_s >= self.bounds.max_seconds:
            return "time"
        if self.cost_usd >= self.bounds.max_cost_usd:
            return "cost"
        return None

    def open_points(self) -> list[str]:
        """What is still unresolved: members with no entry in the last
        round, plus the bound reason if one fired."""
        points: list[str] = []
        last = self.rounds_done
        spoken = {e.agent_id for e in self.entries if e.round_no == last and e.kind == "member"}
        for member in self.member_ids:
            if member not in spoken:
                points.append(f"member {member} has not spoken in round {last}")
        bound = self.bound_hit()
        if bound:
            points.append(f"bound hit: {bound}")
        return points

    def to_dict(self) -> dict[str, Any]:
        return {"thread_id": self.thread_id, "task": self.task,
                "member_ids": self.member_ids,
                "rounds_done": self.rounds_done,
                "cost_usd": round(self.cost_usd, 4),
                "bound": self.bound_hit(),
                "open_points": self.open_points(),
                "entries": [e.to_dict() for e in self.entries]}


Completer = Callable[[list[dict[str, str]]], Awaitable[str]]


async def run_thread(thread: TeamThread, specs: dict[str, Any], completer: Completer,
                     coordinator_prompt: str, stop_flag: Any | None = None) -> dict[str, Any]:
    """Run (or resume) exactly ONE round of a thread, then return.

    One round per call is deliberate: the thread is persisted after
    every entry, so a caller resumes by calling again — after a bound,
    after a stop, or after a process restart — and each call returns
    a typed ``stop_reason`` (``"bound:<kind>"``, ``"stopped"``, or
    ``"round_done"``) + open points, so the caller always knows
    exactly where the thread stopped. Each member speaks once per
    round, seeing the thread so far; the coordinator then synthesizes.

    ``stop_flag`` is any object with an ``is_set()`` method (e.g.
    ``threading.Event``) — the hard-stop button. It is checked between
    members, never mid-completion.
    """
    while True:
        bound = thread.bound_hit()
        if bound:
            thread.append(ThreadEntry(kind="bound", agent_id="system",
                                      content=f"Stopped on bound: {bound}",
                                      round_no=thread.rounds_done))
            return {**thread.to_dict(), "stop_reason": f"bound:{bound}"}
        if stop_flag is not None and stop_flag.is_set():
            thread.append(ThreadEntry(kind="bound", agent_id="system",
                                      content="Stopped by hard-stop request.",
                                      round_no=thread.rounds_done))
            return {**thread.to_dict(), "stop_reason": "stopped"}
        round_no = thread.rounds_done + 1
        transcript = "\n\n".join(
            f"[{e.agent_id}] {e.content}" for e in thread.entries if e.kind in ("member", "coordinator"))
        for member_id in thread.member_ids:
            if stop_flag is not None and stop_flag.is_set():
                break
            spec = specs[member_id]
            system = getattr(spec, "system_prompt", str(spec))
            output = await completer([
                {"role": "system", "content": system},
                {"role": "user", "content": (
                    f"Task: {thread.task}\n\nThread so far:\n{transcript or '(nothing yet)'}\n\n"
                    f"Round {round_no}: add your contribution.")},
            ])
            thread.append(ThreadEntry(kind="member", agent_id=member_id,
                                      content=output or "", round_no=round_no))
        if stop_flag is not None and stop_flag.is_set():
            thread.append(ThreadEntry(kind="bound", agent_id="system",
                                      content="Stopped by hard-stop request.",
                                      round_no=thread.rounds_done))
            return {**thread.to_dict(), "stop_reason": "stopped"}
        transcript = "\n\n".join(
            f"[{e.agent_id}] {e.content}" for e in thread.entries if e.kind in ("member", "coordinator"))
        synthesis = await completer([
            {"role": "system", "content": coordinator_prompt},
            {"role": "user", "content": f"Task: {thread.task}\n\nThread:\n{transcript}\n\nSynthesize."},
        ])
        thread.append(ThreadEntry(kind="coordinator", agent_id="coordinator",
                                  content=synthesis or "", round_no=round_no))
        bound = thread.bound_hit()
        if bound:
            return {**thread.to_dict(), "stop_reason": f"bound:{bound}"}
        return {**thread.to_dict(), "stop_reason": "round_done"}
