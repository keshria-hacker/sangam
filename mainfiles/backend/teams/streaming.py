"""
teams/streaming.py — SSE streaming for team runs (Phase 6.4a).

Yields per-specialist output as SSE events:
- specialist_start: {agent_id, role}
- specialist_chunk: {agent_id, text}
- specialist_done: {agent_id, output, elapsed_s}
- specialist_error: {agent_id, error}
- synthesis_start / synthesis_chunk / synthesis_done
- team_done: {elapsed_s}

Supports per-agent stop via task cancellation and single-agent retry.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

from .definitions import AgentSpec, TeamDefinition, get_team
from .runner import TeamError
from ..feature_flags import is_enabled


async def _stream_specialist(
    spec: AgentSpec,
    task: str,
    model_id: str,
    db: Any,
) -> AsyncIterator[dict]:
    """Stream a single specialist's output."""
    from ..llm import stream_completion

    yield {"type": "specialist_start", "agent_id": spec.id, "role": spec.role}
    started = time.monotonic()
    parts: list[str] = []

    try:
        async for chunk in stream_completion(
            model_id,
            [
                {"role": "system", "content": spec.system_prompt},
                {"role": "user", "content": task},
            ],
            db,
            temperature=spec.temperature,
            max_tokens=2000,
        ):
            text = chunk if isinstance(chunk, str) else getattr(chunk, "text", None)
            if text:
                parts.append(text)
                yield {"type": "specialist_chunk", "agent_id": spec.id, "text": text}
    except asyncio.CancelledError:
        yield {"type": "specialist_stopped", "agent_id": spec.id}
        raise
    except Exception as exc:
        yield {"type": "specialist_error", "agent_id": spec.id, "error": str(exc)}
        return

    output = "".join(parts).strip()
    elapsed = time.monotonic() - started
    if not output:
        yield {"type": "specialist_error", "agent_id": spec.id, "error": "Empty response"}
    else:
        yield {
            "type": "specialist_done",
            "agent_id": spec.id,
            "output": output,
            "elapsed_s": round(elapsed, 2),
        }


async def stream_team_run(
    team_id: str,
    task: str,
    model_id: str,
    db: Any,
) -> AsyncIterator[dict]:
    """Stream a full team run as SSE events."""
    if not is_enabled("multi_agent"):
        yield {"type": "error", "error": "Multi-agent teams are not enabled"}
        return

    team: TeamDefinition | None = get_team(team_id)
    if team is None:
        yield {"type": "error", "error": f"Unknown team: {team_id}"}
        return

    task = (task or "").strip()
    if not task:
        yield {"type": "error", "error": "Empty task."}
        return

    started = time.monotonic()
    yield {"type": "team_start", "team_id": team_id, "specialists": [s.id for s in team.specialists]}

    # Fan-out: run specialists concurrently, streaming each
    specialist_outputs: dict[str, str] = {}

    async def _collect(spec: AgentSpec):
        async for event in _stream_specialist(spec, task, model_id, db):
            if event["type"] == "specialist_done":
                specialist_outputs[spec.id] = event["output"]
            yield event

    # Run all specialists concurrently, yielding events as they arrive
    queues: dict[str, asyncio.Queue] = {s.id: asyncio.Queue() for s in team.specialists}

    async def _producer(spec: AgentSpec):
        try:
            async for event in _stream_specialist(spec, task, model_id, db):
                await queues[spec.id].put(event)
                if event["type"] == "specialist_done":
                    specialist_outputs[spec.id] = event["output"]
        finally:
            await queues[spec.id].put(None)  # Sentinel

    producers = [asyncio.create_task(_producer(spec)) for spec in team.specialists]

    try:
        # Yield events as they arrive from any specialist
        active = set(s.id for s in team.specialists)
        while active:
            for agent_id in list(active):
                try:
                    event = queues[agent_id].get_nowait()
                    if event is None:
                        active.discard(agent_id)
                    else:
                        yield event
                except asyncio.QueueEmpty:
                    pass
            if active:
                await asyncio.sleep(0.05)
    finally:
        for p in producers:
            if not p.done():
                p.cancel()

    # Fan-in: coordinator synthesizes
    succeeded = [sid for sid, out in specialist_outputs.items() if out]
    if not succeeded:
        yield {"type": "error", "error": "All specialists failed."}
        return

    yield {"type": "synthesis_start"}
    try:
        from ..llm import stream_completion
        synthesis_parts = []
        # Build synthesis prompt from specialist outputs
        synth_prompt = f"Task: {task}\n\nSpecialist outputs:\n"
        for sid, output in specialist_outputs.items():
            synth_prompt += f"\n--- {sid} ---\n{output}\n"

        async for chunk in stream_completion(
            model_id,
            [
                {"role": "system", "content": "Synthesize the specialist outputs into a coherent response."},
                {"role": "user", "content": synth_prompt},
            ],
            db,
            temperature=0.7,
            max_tokens=2000,
        ):
            text = chunk if isinstance(chunk, str) else getattr(chunk, "text", None)
            if text:
                synthesis_parts.append(text)
                yield {"type": "synthesis_chunk", "text": text}

        yield {"type": "synthesis_done", "output": "".join(synthesis_parts)}
    except Exception as exc:
        yield {"type": "error", "error": f"Synthesis failed: {exc}"}
        return

    yield {"type": "team_done", "elapsed_s": round(time.monotonic() - started, 2)}


def format_sse(event: dict) -> str:
    """Format an event as SSE."""
    return f"data: {json.dumps(event)}\n\n"
