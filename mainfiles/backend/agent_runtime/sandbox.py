"""agent_runtime/sandbox.py — per-run sandbox/worktree default (Batch 10).

OpenHands portable idea, Sangam-native: a code-agent run's DEFAULT
execution context is an isolated context, not the bare workspace.

* :func:`default_execution_context` — given a workspace, prefer a
  git worktree for the run (via ``backend.worktrees``) when the
  workspace is a git repo; otherwise fall back to the workspace
  itself with an explicit ``workspace-fallback`` warning. The
  fallback is recorded on every result — never silent.
* :func:`detect_test_command` — the verify-style exit gate: find the
  project's OWN test command (package.json ``test`` script, pytest
  via pyproject, ``make test``, ``npm test``) without inventing one.
  Returns None when no test command is discoverable — a run with no
  discoverable command reports "no test command found", never a fake
  pass.
* :func:`run_verify_gate` — run the detected (or caller-supplied)
  command through ``security_guardrails.run_isolated_command`` so
  Docker isolation is used when a daemon is actually present and the
  workspace fallback + warning is used otherwise. Docker isolation is
  NOT claimed as verified live on machines without Docker.

No shell is used anywhere here: commands are argv lists only.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SandboxContext:
    """The execution context a code-agent run should use."""

    mode: str  # "worktree" | "workspace-fallback"
    path: str
    warning: str = ""
    worktree_name: str = ""
    repo: str = ""

    def to_dict(self) -> dict:
        return {"mode": self.mode, "path": self.path,
                "warning": self.warning,
                "worktree_name": self.worktree_name, "repo": self.repo}


def _is_git_repo(path: Path) -> bool:
    return (path / ".git").exists() or bool(
        shutil.which("git") and _git_ok(path))


def _git_ok(path: Path) -> bool:
    import subprocess
    try:
        proc = subprocess.run(["git", "-C", str(path), "rev-parse", "--git-dir"],
                              capture_output=True, text=True, timeout=15)
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def default_execution_context(workspace: str | Path, run_id: str,
                              worktrees_parent: str | Path | None = None) -> SandboxContext:
    """Return the DEFAULT execution context for a code-agent run.

    Git repo + worktrees parent available -> a fresh detached worktree
    named after the run (ownership handoff primitive, orca §10). Any
    failure creating the worktree falls back to the workspace with a
    warning that names the failure — the run never silently runs
    un-sandboxed while claiming otherwise.
    """
    ws = Path(workspace)
    ws.mkdir(parents=True, exist_ok=True)
    parent = Path(worktrees_parent) if worktrees_parent else ws.parent / ".sangam-worktrees"
    if _is_git_repo(ws):
        try:
            from ..worktrees import create_worktree
            name = f"run-{run_id}"[:64]
            wt = create_worktree(ws, parent, name)
            return SandboxContext(mode="worktree", path=str(wt.path),
                                  worktree_name=name, repo=str(ws))
        except Exception as exc:  # noqa: BLE001 — fallback is the designed path
            return SandboxContext(
                mode="workspace-fallback", path=str(ws), repo=str(ws),
                warning=f"Worktree creation failed ({exc}); running in the "
                        "workspace itself. Changes land directly in the workspace.")
    return SandboxContext(
        mode="workspace-fallback", path=str(ws), repo="",
        warning="Workspace is not a git repo: no worktree could be created, "
                "so the run executes in the workspace itself. Commit or copy "
                "results before trusting them.")


def detect_test_command(workspace: str | Path) -> dict:
    """Detect the project's own test command. Never invents one.

    Order: package.json ``scripts.test`` -> pyproject with pytest/dev
    dependency -> Makefile ``test:`` target -> None (honest absence).
    Returns {command: [argv...] | None, source: str}.
    """
    ws = Path(workspace)
    pkg = ws / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            test_script = (data.get("scripts") or {}).get("test")
            if isinstance(test_script, str) and test_script.strip():
                # npm test runs the declared script; argv stays shell-free
                # by invoking npm itself (the script's own content is the
                # project's, not Sangam's — it runs under the sandbox).
                return {"command": ["npm", "test"], "source": "package.json scripts.test"}
        except (OSError, ValueError):
            pass
    pyproject = ws / "pyproject.toml"
    if pyproject.is_file():
        try:
            text = pyproject.read_text(encoding="utf-8")
            if "pytest" in text:
                return {"command": ["python", "-m", "pytest", "-q"],
                        "source": "pyproject.toml (pytest)"}
        except OSError:
            pass
    if (ws / "test_pytest.py").exists() or (ws / "tests").is_dir():
        return {"command": ["python", "-m", "pytest", "-q"],
                "source": "tests/ directory present"}
    makefile = ws / "Makefile"
    if makefile.is_file():
        try:
            if any(line.startswith("test:") for line in
                   makefile.read_text(encoding="utf-8").splitlines()):
                return {"command": ["make", "test"], "source": "Makefile test target"}
        except OSError:
            pass
    return {"command": None, "source": "no test command discoverable"}


def run_verify_gate(workspace: str | Path, command: list[str] | None = None,
                    timeout: float = 300.0, docker_present: bool | None = None) -> dict:
    """Verify-style exit gate: run the project's own test command.

    ``command`` overrides detection only when the caller explicitly
    supplies it (the route requires confirm=true for overrides).
    Returns {passed, command, source, isolation, warning, stdout_tail,
    stderr_tail, returncode}. ``passed`` is False — never None-as-pass —
    when no command is discoverable or the command fails.
    """
    ws = Path(workspace)
    detected = detect_test_command(ws)
    cmd = list(command) if command else detected["command"]
    source = "caller-supplied" if command else detected["source"]
    if not cmd:
        return {"passed": False, "command": None, "source": source,
                "isolation": "", "warning": "",
                "detail": "No test command discoverable in this workspace; "
                          "the verify gate cannot pass without one.",
                "stdout_tail": "", "stderr_tail": "", "returncode": None}
    from ..security_guardrails import run_isolated_command
    result = run_isolated_command(cmd, ws, timeout=timeout,
                                  docker_present=docker_present)
    return {"passed": result.returncode == 0, "command": cmd,
            "source": source, "isolation": result.isolation,
            "warning": result.warning or "",
            "stdout_tail": (result.stdout or "")[-2000:],
            "stderr_tail": (result.stderr or "")[-1000:],
            "returncode": result.returncode}
