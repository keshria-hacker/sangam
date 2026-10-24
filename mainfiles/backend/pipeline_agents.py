"""
pipeline_agents.py — real per-task agent runs for the engineering pipeline.

Path taken (per the Wave-1 brief): the EXISTING agent-runner interface
``code_agent.run_agent`` — the generalized loop that ``run_code_agent``
wraps. ``run_code_agent`` itself is NOT used here because it hard-codes
the default approval gates (write/edit/bash block on a user approval
that never arrives in a pipeline run); the pipeline's explicit stage
advances are the ask-before-act pause points, so the run is invoked
with ``require_approval=[]`` and the code-agent toolset + TDD system
text. No synthesis shortcut: if the agent run fails, the ledger row
records the error and test_passed=False — it never invents output.

Diff discipline: before the run, the current content of the task's
target files is snapshotted; after the run, a real unified diff
(difflib) is computed per changed/created file, plus any further files
the agent touched via write_file/edit_file tool calls. BASE/HEAD refs
in the review package are hashes of the pre-run snapshot and the
post-run diff — scoped to the task's files, never a repo-wide git diff
(other workers share this checkout, so a repo-wide diff would attribute
their changes to this pipeline).
"""
from __future__ import annotations

import difflib
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TaskAgentResult:
    task_id: str
    diff: str = ""
    answer: str = ""
    error: str = ""
    tool_steps: list[dict] = field(default_factory=list)
    touched_files: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.error


def build_diff_from_snapshots(before: dict[str, str | None],
                              after: dict[str, str | None]) -> str:
    """Unified diff over snapshotted files. None = file did not exist."""
    chunks = []
    for path in sorted(set(before) | set(after)):
        old = before.get(path)
        new = after.get(path)
        if old == new:
            continue
        old_lines = (old or "").splitlines(keepends=True)
        new_lines = (new or "").splitlines(keepends=True)
        diff = "".join(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{path}", tofile=f"b/{path}"))
        if diff:
            chunks.append(diff)
    return "\n".join(chunks)


def _workspace_root() -> Path:
    from .config import settings
    return Path(settings.WORKSPACE_ROOT).resolve()


def _read_workspace(path: str) -> str | None:
    root = _workspace_root()
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if not target.is_file():
        return None
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


async def run_task_agent(task_id: str, brief: str, model_id: str, db: Any,
                         files: list[str] | None = None,
                         fresh_context: bool = False) -> TaskAgentResult:
    """Run a REAL code-agent run for one task. Returns its diff.

    fresh_context (fix rounds 4-5): the brief carries no prior-run
    transcript — only the task, the review findings are the caller's
    responsibility to include in the brief, and no step history is
    reused, because each call builds a fresh message list anyway.
    """
    from .code_agent import CODE_AGENT_SYSTEM, CODE_AGENT_TOOLS, run_agent

    files = list(files or [])
    before = {f: _read_workspace(f) for f in files}
    touched: list[str] = []
    steps: list[dict] = []
    answer = ""
    error = ""
    try:
        extra = (
            "TDD MODE (enforced, not a suggestion): write a failing test "
            "FIRST (RED), then implement until it passes (GREEN), then "
            "refactor. Show test evidence in your final answer.")
        if fresh_context:
            extra += (" This is a fresh-context fix round: do not rely on "
                      "any prior run's transcript; work from this brief alone.")
        async for step in run_agent(
            brief, model_id, db,
            tool_names=CODE_AGENT_TOOLS,
            system_prompt=CODE_AGENT_SYSTEM,
            max_iterations=12,
            extra_system=extra,
            require_approval=[],
        ):
            steps.append({"kind": step.kind, "content": step.content,
                          "tool": step.tool_name, "args": step.tool_args})
            if step.kind in ("answer", "done") and step.content:
                answer = step.content
            if step.kind == "error":
                error = step.content
            if step.kind == "tool_call" and step.tool_name in (
                    "write_file", "edit_file"):
                p = (step.tool_args or {}).get("path")
                if p and p not in touched:
                    touched.append(p)
    except Exception as exc:  # noqa: BLE001 — recorded, never synthesized
        error = f"agent run failed: {exc}"
    watched = sorted(set(files) | set(touched))
    after = {f: _read_workspace(f) for f in watched}
    for f in watched:
        if f not in before:
            before[f] = None
    diff = build_diff_from_snapshots(before, after)
    return TaskAgentResult(task_id=task_id, diff=diff, answer=answer,
                           error=error, tool_steps=steps,
                           touched_files=watched)


def run_tests(command: str, timeout: int = 300) -> tuple[bool, str]:
    """Run a test command (no shell) and return (passed, output).

    Empty command = no test evidence = not passed: TDD enforcement
    requires a real test command, not an assumption.
    """
    command = (command or "").strip()
    if not command:
        return False, "no test command supplied: no test evidence recorded"
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return False, f"unparseable test command: {exc}"
    try:
        proc = subprocess.run(
            argv, cwd=str(_workspace_root()), capture_output=True,
            text=True, timeout=timeout)
    except FileNotFoundError as exc:
        return False, f"test command not found: {exc}"
    except subprocess.TimeoutExpired:
        return False, f"test command timed out after {timeout}s"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out[-4000:]
