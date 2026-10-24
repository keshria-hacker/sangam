"""
worktrees.py — Orca portable residue: git worktrees + diff-line
annotation back to the agent.

What is built here (the portable part of Orca):
- git worktree create / list / remove, via the git CLI only (no new
  dependency, no server-side git library);
- a per-worktree agent run: run a command with its cwd pinned to the
  worktree (the agent's working directory IS the worktree, so its
  edits land on that branch, never on the main checkout);
- diff-line annotation: a review comment references an EXACT
  file + line, validated against a unified diff — a comment whose
  line is not in the diff's new-file lines is rejected, not stored
  (an annotation pointing nowhere helps nobody).

What stays DEFERRED (needs host setup decisions; do NOT silently
expand attack surface): SSH remote execution and the mobile
companion. No SSH command, key handling, or remote host is touched
anywhere in this module — a caller asking for SSH gets a
``NotImplementedError`` naming the deferral, not a half-built tunnel.

Safety: worktree paths are created only under a caller-supplied
parent directory; ``remove`` refuses paths outside that parent.
All git invocations are argv lists with timeouts — never shell.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DIFF_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
DIFF_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")


class WorktreeError(RuntimeError):
    """A worktree operation failed in a way the caller can act on."""


@dataclass
class Worktree:
    path: str
    branch: str
    head: str
    bare: bool = False
    detached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "branch": self.branch, "head": self.head,
                "bare": self.bare, "detached": self.detached}


def _run_git(repo: str | Path, args: list[str], timeout: float = 60.0) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(repo)] + args,
                              capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise WorktreeError(f"git {' '.join(args)} failed: {exc}") from exc


def list_worktrees(repo: str | Path) -> list[Worktree]:
    """Parse ``git worktree list --porcelain``. Raises WorktreeError
    when git fails (e.g. not a repo) instead of returning a fake
    empty list."""
    proc = _run_git(repo, ["worktree", "list", "--porcelain"])
    if proc.returncode != 0:
        raise WorktreeError(f"git worktree list failed: {proc.stderr.strip()[:500]}")
    out: list[Worktree] = []
    current: dict[str, Any] = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            if current:
                out.append(Worktree(path=current.get("path", ""), branch=current.get("branch", ""),
                                    head=current.get("head", ""), bare=current.get("bare", False),
                                    detached=current.get("detached", False)))
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current["path"] = value
        elif key == "HEAD":
            current["head"] = value
        elif key == "branch":
            current["branch"] = value.removeprefix("refs/heads/")
        elif key == "bare":
            current["bare"] = True
        elif key == "detached":
            current["detached"] = True
    if current:
        out.append(Worktree(path=current.get("path", ""), branch=current.get("branch", ""),
                            head=current.get("head", ""), bare=current.get("bare", False),
                            detached=current.get("detached", False)))
    return out


def create_worktree(repo: str | Path, parent_dir: str | Path, name: str,
                    branch: str | None = None, timeout: float = 120.0) -> Worktree:
    """Create a worktree at ``<parent_dir>/<name>``. ``name`` must be
    a plain directory name (no separators, no traversal). With
    ``branch`` given, a new branch is created (``-b``); without it,
    the worktree is detached at HEAD. Raises on git failure."""
    name = (name or "").strip()
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise WorktreeError("worktree name must be a plain directory name")
    parent = Path(parent_dir)
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / name
    if target.exists():
        raise WorktreeError(f"worktree path already exists: {target}")
    args = ["worktree", "add"]
    if branch:
        args += ["-b", branch]
    else:
        args += ["--detach"]
    args.append(str(target))
    proc = _run_git(repo, args, timeout=timeout)
    if proc.returncode != 0:
        raise WorktreeError(f"git worktree add failed: {proc.stderr.strip()[:500]}")
    matches = [w for w in list_worktrees(repo) if Path(w.path) == target]
    if not matches:
        raise WorktreeError("worktree created but not listed by git")
    return matches[0]


def remove_worktree(repo: str | Path, parent_dir: str | Path, name: str,
                    force: bool = False, timeout: float = 120.0) -> dict[str, Any]:
    """Remove a worktree by name. Refuses any path outside the parent
    dir (traversal guard); without ``force``, git itself refuses a
    dirty worktree, and that refusal is surfaced, not overridden."""
    name = (name or "").strip()
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise WorktreeError("worktree name must be a plain directory name")
    parent = Path(parent_dir).resolve()
    target = (parent / name).resolve()
    if parent not in target.parents and target != parent:
        raise WorktreeError("worktree path is outside the parent directory")
    if not target.exists():
        raise WorktreeError(f"no such worktree: {target}")
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(target))
    proc = _run_git(repo, args, timeout=timeout)
    if proc.returncode != 0:
        raise WorktreeError(f"git worktree remove failed: {proc.stderr.strip()[:500]}")
    return {"removed": str(target), "force": force}


def run_in_worktree(worktree_path: str | Path, command: list[str],
                    timeout: float = 120.0) -> dict[str, Any]:
    """Per-worktree agent run: one argv command with cwd pinned to the
    worktree. No shell, no env inheritance beyond a scrubbed PATH/HOME
    (mirroring the security workspace fallback). Returns stdout/stderr
    truncated, never a fabricated success."""
    ws = Path(worktree_path)
    if not ws.is_dir():
        raise WorktreeError(f"not a worktree directory: {ws}")
    if not command:
        raise WorktreeError("empty command")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(ws)}
    try:
        proc = subprocess.run(list(command), capture_output=True, text=True,
                              timeout=timeout, cwd=str(ws), env=env)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise WorktreeError(f"worktree command failed: {exc}") from exc
    return {"worktree": str(ws), "command": list(command),
            "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-2000:],
            "returncode": proc.returncode}


# ------------------------------------------------------- diff-line annotation

def diff_new_lines(diff_text: str) -> dict[str, set[int]]:
    """Map file -> set of new-file line numbers present in a unified
    diff. Only ``+`` lines inside hunks count; ``+++`` headers and
    context lines do not."""
    files: dict[str, set[int]] = {}
    current_file: str | None = None
    new_lineno = 0
    for line in (diff_text or "").splitlines():
        file_match = DIFF_FILE_RE.match(line)
        if file_match:
            current_file = file_match.group(1)
            files.setdefault(current_file, set())
            continue
        hunk = DIFF_HUNK_RE.match(line)
        if hunk:
            new_lineno = int(hunk.group(1))
            continue
        if current_file is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            files[current_file].add(new_lineno)
            new_lineno += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue  # removed line: new-file numbering does not advance
        else:
            new_lineno += 1
    return files


@dataclass
class ReviewComment:
    file: str
    line: int
    comment: str
    author: str = "reviewer"

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "line": self.line,
                "comment": self.comment, "author": self.author}


def annotate_diff(diff_text: str, comments: list[ReviewComment]) -> dict[str, Any]:
    """Validate review comments against a diff. A comment is kept
    only when its exact file+line is a new-file line in the diff;
    anything else is rejected (listed, not silently stored), so an
    annotation can never point at a line the change does not touch."""
    valid_lines = diff_new_lines(diff_text or "")
    kept: list[ReviewComment] = []
    rejected: list[dict[str, Any]] = []
    for comment in comments:
        lines = valid_lines.get(comment.file, set())
        if comment.line in lines:
            kept.append(comment)
        else:
            rejected.append({**comment.to_dict(),
                             "reason": "line is not a new-file line in the diff"})
    return {"kept": [c.to_dict() for c in kept], "rejected": rejected}


def ssh_remote_execute(*args: Any, **kwargs: Any) -> Any:
    """DEFERRED — SSH remote execution needs host setup decisions
    (which hosts, which keys, who approves). It is refused here
    rather than half-built: callers get the deferral, not a tunnel."""
    raise NotImplementedError(
        "SSH remote execution is DEFERRED: it needs host setup decisions "
        "(approved hosts, key management, per-run approval) that have not "
        "been made. It is not silently available.")


def mobile_companion(*args: Any, **kwargs: Any) -> Any:
    """DEFERRED — the mobile companion needs host setup decisions
    (companion app, pairing model beyond LAN). Refused, not half-built."""
    raise NotImplementedError(
        "The mobile companion is DEFERRED: it needs host setup decisions "
        "that have not been made. Use LAN pairing / phone-approval tokens "
        "for phone decisions in the meantime.")
