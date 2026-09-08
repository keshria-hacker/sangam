"""
skills/router.py — routes skill execution requests to the hardened SkillExecutor.
Provides the SkillRouter facade that the API layer calls.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.skills.executor import ExecutionResult, get_executor

logger = logging.getLogger(__name__)


class SkillRouter:
    """
    Facade over SkillExecutor that also maintains execution history.
    This is the public API for the skills subsystem; the backend API
    layer calls execute() / chain() through this class.
    """

    def __init__(self) -> None:
        self.executor = get_executor()
        self.history: list[ExecutionResult] = []

    async def execute(
        self,
        skill_id: str,
        params: dict[str, Any],
        stream: bool = False,
        timeout: float | None = None,
    ) -> ExecutionResult:
        """
        Execute a skill with full hardening (timeout, retries, structured errors).

        Args:
            skill_id: The skill ID to execute
            params: Parameter dict for the skill
            stream: Unused — kept for backward compatibility
            timeout: Optional per-call timeout override (seconds)

        Returns:
            ExecutionResult with result/error/timing metadata
        """
        del stream  # Kept for backward compatibility; executor handles internally
        result = await self.executor.execute(skill_id, params, timeout=timeout)
        self.history.append(result)
        return result

    async def chain(
        self,
        chain: list[dict[str, Any]],
        timeout_per_skill: float | None = None,
    ) -> list[ExecutionResult]:
        """
        Execute a chain of skills sequentially, passing context forward.

        Each step can access previous step results via {skill_id}_result
        in its params.

        Args:
            chain: List of steps, each with "skill" and optional "params"
            timeout_per_skill: Optional timeout per individual step

        Returns:
            List of ExecutionResult (one per step)
        """
        results = await self.executor.execute_chain(chain, timeout_per_skill)
        self.history.extend(results)
        return results

    def get_history(self, limit: int = 20) -> list[ExecutionResult]:
        """Return recent execution history."""
        return self.history[-limit:]

    def clear_history(self) -> None:
        """Clear execution history."""
        self.history.clear()


_router: SkillRouter | None = None


def get_router() -> SkillRouter:
    """Get or create the singleton SkillRouter."""
    global _router
    if _router is None:
        _router = SkillRouter()
    return _router