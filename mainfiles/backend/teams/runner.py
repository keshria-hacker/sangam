"""
teams/runner.py — fan-out / fan-in team execution (orca fleet pattern).

Each specialist runs as an independent LLM call with its role prompt;
specialists run concurrently via asyncio.gather, then the coordinator
synthesizes. Failures are per-agent: a failed specialist is reported as
such and the coordinator works with what succeeded.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .definitions import AgentSpec, TeamDefinition, get_team
from ..feature_flags import is_enabled

logger = logging.getLogger(__name__)


class TeamError(RuntimeError):
    """A team run failed in a way the user can act on."""


@dataclass
class AgentResult:
    agent_id: str
    role: str
    output: str = ""
    error: str | None = None
    elapsed_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class TeamResult:
    team_id: str
    task: str
    synthesis: str = ""
    specialists: list[AgentResult] = field(default_factory=list)
    elapsed_s: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "task": self.task,
            "synthesis": self.synthesis,
            "specialists": [
                {
                    "agent_id": r.agent_id,
                    "role": r.role,
                    "output": r.output,
                    "error": r.error,
                    "elapsed_s": round(r.elapsed_s, 2),
                }
                for r in self.specialists
            ],
            "elapsed_s": round(self.elapsed_s, 2),
            "error": self.error,
        }


async def _complete_once(
    model_id: str,
    messages: list[dict],
    db: Any,
    temperature: float,
    max_tokens: int = 2000,
) -> str:
    """Collect a streamed completion into a single string."""
    from ..llm import stream_completion

    parts: list[str] = []
    async for chunk in stream_completion(
        model_id, messages, db, temperature=temperature, max_tokens=max_tokens
    ):
        text = chunk if isinstance(chunk, str) else getattr(chunk, "text", None)
        if text:
            parts.append(text)
    return "".join(parts).strip()


async def _run_specialist(
    spec: AgentSpec,
    task: str,
    model_id: str,
    db: Any,
) -> AgentResult:
    started = time.monotonic()
    try:
        output = await _complete_once(
            model_id,
            [
                {"role": "system", "content": spec.system_prompt},
                {"role": "user", "content": task},
            ],
            db,
            temperature=spec.temperature,
        )
        if not output:
            return AgentResult(spec.id, spec.role, error="Empty response", elapsed_s=time.monotonic() - started)
        return AgentResult(spec.id, spec.role, output=output, elapsed_s=time.monotonic() - started)
    except Exception as exc:  # noqa: BLE001 — per-agent failure, not fatal
        logger.warning("specialist %s failed: %s", spec.id, exc)
        return AgentResult(spec.id, spec.role, error=str(exc), elapsed_s=time.monotonic() - started)


async def run_team(
    team_id: str,
    task: str,
    model_id: str,
    db: Any,
    max_tokens: int = 2000,
) -> TeamResult:
    """Run a team: fan-out to specialists, fan-in through the coordinator."""
    from ..config import settings

    if not is_enabled("multi_agent"):
        raise TeamError("Multi-agent teams are not enabled (FEATURE_MULTI_AGENT=false).")
    team: TeamDefinition | None = get_team(team_id)
    if team is None:
        raise TeamError(f"Unknown team: {team_id}")
    task = (task or "").strip()
    if not task:
        raise TeamError("Empty task.")
    if not model_id:
        raise TeamError("No model selected.")

    started = time.monotonic()
    # Fan-out: specialists run concurrently (orca fleet pattern).
    specialist_results = await asyncio.gather(
        *(_run_specialist(spec, task, model_id, db) for spec in team.specialists)
    )
    succeeded = [r for r in specialist_results if r.ok and r.output]
    if not succeeded:
        return TeamResult(
            team_id, task, specialists=list(specialist_results),
            elapsed_s=time.monotonic() - started,
            error="All specialists failed.",
        )

    # Fan-in: coordinator synthesizes.
    combined = "\n\n".join(
        f"## {r.role}\n{r.output}" for r in succeeded
    )
    try:
        synthesis = await _complete_once(
            model_id,
            [
                {"role": "system", "content": team.coordinator_prompt},
                {
                    "role": "user",
                    "content": f"Original task: {task}\n\nSpecialist outputs:\n{combined}",
                },
            ],
            db,
            temperature=0.5,
            max_tokens=max_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("coordinator failed: %s", exc)
        return TeamResult(
            team_id, task, specialists=list(specialist_results),
            elapsed_s=time.monotonic() - started,
            error=f"Coordinator failed: {exc}",
        )
    return TeamResult(
        team_id, task, synthesis=synthesis,
        specialists=list(specialist_results),
        elapsed_s=time.monotonic() - started,
    )
