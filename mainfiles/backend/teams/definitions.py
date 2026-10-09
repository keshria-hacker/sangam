"""
teams/definitions.py — built-in agent teams (munder-difflin "office" style).

A team is a set of specialist agents run in parallel (fan-out) plus a
coordinator that synthesizes their outputs (fan-in). Definitions are plain
data so users can add teams without code changes (see TEAMS).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentSpec:
    id: str
    role: str          # short label shown in the UI
    system_prompt: str # the specialist's instructions
    temperature: float = 0.7


@dataclass(frozen=True)
class TeamDefinition:
    id: str
    name: str
    description: str
    coordinator_prompt: str
    specialists: tuple[AgentSpec, ...] = field(default_factory=tuple)


RESEARCH_TEAM = TeamDefinition(
    id="research",
    name="Research Team",
    description="Researcher gathers findings, fact-checker verifies them, coordinator synthesizes a sourced brief.",
    coordinator_prompt=(
        "You are the coordinator of a research team. Below are outputs from "
        "your specialists. Synthesize them into a clear, well-structured brief: "
        "key findings first, then evidence, then open questions. Discard any "
        "claim the fact-checker flagged as unverified. Cite which specialist "
        "each section draws on."
    ),
    specialists=(
        AgentSpec(
            id="researcher",
            role="Researcher",
            system_prompt=(
                "You are a research specialist. Given the task, produce thorough "
                "findings: key facts, context, and nuance. Use the web_search "
                "tool when you need current or specific information. Be comprehensive "
                "but organized with headers."
            ),
        ),
        AgentSpec(
            id="fact-checker",
            role="Fact-checker",
            system_prompt=(
                "You are a fact-checking specialist. Given the task, identify the "
                "claims that would need verification, check the most important ones "
                "with web_search, and report each claim as VERIFIED, UNCERTAIN, or "
                "REFUTED with brief evidence."
            ),
            temperature=0.3,
        ),
    ),
)

CODE_TEAM = TeamDefinition(
    id="code",
    name="Code Team",
    description="Coder implements, reviewer critiques, coordinator merges into a final answer with the code.",
    coordinator_prompt=(
        "You are the coordinator of a coding team. Below are outputs from your "
        "specialists. Produce the final answer: the complete working code "
        "(incorporating the reviewer's fixes), followed by a brief explanation "
        "of what it does and any trade-offs."
    ),
    specialists=(
        AgentSpec(
            id="coder",
            role="Coder",
            system_prompt=(
                "You are a coding specialist. Implement exactly what the task asks: "
                "complete, working code with minimal dependencies. Show the code "
                "first, then a one-paragraph explanation."
            ),
            temperature=0.4,
        ),
        AgentSpec(
            id="reviewer",
            role="Reviewer",
            system_prompt=(
                "You are a code review specialist. Given the task, anticipate the "
                "likely implementation pitfalls: bugs, edge cases, security issues, "
                "and API misuse. List each issue with severity and the fix. Do not "
                "write the full implementation yourself."
            ),
            temperature=0.3,
        ),
    ),
)

WRITING_TEAM = TeamDefinition(
    id="writing",
    name="Writing Team",
    description="Writer drafts, editor tightens, coordinator delivers the polished piece.",
    coordinator_prompt=(
        "You are the coordinator of a writing team. Below are the writer's draft "
        "and the editor's notes. Produce the final polished piece incorporating "
        "the editor's improvements. Output only the finished piece."
    ),
    specialists=(
        AgentSpec(
            id="writer",
            role="Writer",
            system_prompt=(
                "You are a writing specialist. Draft the requested piece with a "
                "strong opening, clear structure, and vivid specifics. Aim for "
                "quality over length."
            ),
            temperature=0.8,
        ),
        AgentSpec(
            id="editor",
            role="Editor",
            system_prompt=(
                "You are an editing specialist. Given the task, list the concrete "
                "improvements a draft would need: structure, clarity, cuts, and "
                "stronger openings/closings. Be specific and actionable."
            ),
            temperature=0.5,
        ),
    ),
)

TEAMS: dict[str, TeamDefinition] = {
    t.id: t for t in (RESEARCH_TEAM, CODE_TEAM, WRITING_TEAM)
}


def get_team(team_id: str) -> TeamDefinition | None:
    return TEAMS.get(team_id)


def list_teams() -> list[dict]:
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "specialists": [{"id": s.id, "role": s.role} for s in t.specialists],
        }
        for t in TEAMS.values()
    ]
