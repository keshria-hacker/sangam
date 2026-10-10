"""
spec_wizard.py — guided spec → plan → tasks (spec-kit patterns, Sangam-native).

A spec is a structured document: problem, goals, constraints, plan, tasks.
The wizard helps build it step by step, then it can drive the Code Agent.
"""
from __future__ import annotations

SPEC_TEMPLATE = """# {title}

## Problem
{problem}

## Goals
{goals}

## Constraints
{constraints}

## Plan
{plan}

## Tasks
{tasks}
"""

def build_spec(title: str, problem: str, goals: list[str],
               constraints: list[str], plan: list[str],
               tasks: list[str]) -> str:
    """Render a spec document from wizard inputs."""
    return SPEC_TEMPLATE.format(
        title=title,
        problem=problem or "_Not specified_",
        goals="\n".join(f"- {g}" for g in goals) or "- _None_",
        constraints="\n".join(f"- {c}" for c in constraints) or "- _None_",
        plan="\n".join(f"{i+1}. {p}" for i, p in enumerate(plan)) or "_None_",
        tasks="\n".join(f"- [ ] {t}" for t in tasks) or "- [ ] _None_",
    )


def spec_to_agent_task(spec: str) -> str:
    """Convert a spec into a Code Agent task prompt."""
    return (
        "Implement the following spec. Work through the tasks in order, "
        "verifying each step.\n\n" + spec
    )
