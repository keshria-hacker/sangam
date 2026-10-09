"""
backend.teams — multi-agent teams (orca fleet / munder-difflin office pattern).

Fan-out: specialist agents run concurrently with role prompts.
Fan-in: a coordinator synthesizes their outputs into the final answer.
Gated by FEATURE_MULTI_AGENT.
"""
from __future__ import annotations

from .definitions import get_team, list_teams
from .runner import AgentResult, TeamError, TeamResult, run_team


def register_teams_extension() -> bool:
    """Project multi-agent teams into the unified extension registry."""
    try:
        from ..extensions import ExtensionKind, ExtensionManifest, extensions
    except ImportError:
        return False
    extensions.register(
        ExtensionManifest(
            name="capability:multi_agent",
            version="1.0.0",
            kind=ExtensionKind.CAPABILITY,
            description=(
                "Multi-agent teams: parallel specialist agents (research, code, "
                "writing) with coordinator synthesis."
            ),
            enabled_by_default=True,
        )
    )
    return True


__all__ = [
    "AgentResult",
    "TeamError",
    "TeamResult",
    "get_team",
    "list_teams",
    "register_teams_extension",
    "run_team",
]
