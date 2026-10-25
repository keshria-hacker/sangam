"""skills/bootstrap.py — bootstrap-command skills + scripts manifest (Batch 10).

ego-lite / orca portable pattern: a skill's body may be SERVED by its
tool at run time instead of pasted from a possibly-stale SKILL.md, so
docs can never drift from the tool. In Sangam form:

* A skill declares ``bootstrap_command`` in frontmatter (a single
  command + args, no shell metacharacters — see :func:`validate_bootstrap_command`).
* :func:`resolve_bootstrap_body` runs it ONLY after approval (the same
  approval-gate pattern as skill script runs): without an approved
  gate it returns ``approval_needed`` + an approval id; the caller
  resolves it via the existing ``POST /api/agent/approve/{id}`` and
  re-calls with the id. Output is capped (4000 chars) and scanned for
  banned patterns before it becomes a skill body.
* :func:`declared_scripts` is the declared ``scripts/`` manifest: when
  a skill ships ``scripts.json`` it is the manifest (entries must
  resolve inside the skill dir); otherwise the manifest is the
  ``scripts/`` directory listing. Convention-only script discovery is
  replaced by this explicit list — taste-skill's script-dealt pattern
  needs a manifest, not a guess.

Commands run with argv only (no shell), a 30s timeout, and a scrubbed
environment; nothing here executes a caller-supplied command string —
the command must already be declared in the skill file on disk.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

BOOTSTRAP_OUTPUT_CAP = 4000
_BOOTSTRAP_TIMEOUT_S = 30
_FORBIDDEN = (";", "&&", "||", "|", "`", "$(", ">", "<", "\n", "\r")
_BANNED_OUTPUT = ("os.system", "os.popen", "eval(", "exec(",
                  "subprocess.call", "pickle.load")


def validate_bootstrap_command(command: str) -> tuple[bool, str]:
    """Validate a declared bootstrap command. Returns (ok, reason)."""
    cmd = (command or "").strip()
    if not cmd:
        return False, "bootstrap_command is empty"
    for token in _FORBIDDEN:
        if token in cmd:
            return False, f"bootstrap_command must be a single command without {token!r}"
    parts = cmd.split()
    if not parts:
        return False, "bootstrap_command is empty"
    return True, ""


def declared_scripts(skill_dir: str | Path) -> list[dict]:
    """Declared scripts manifest for a skill dir.

    ``scripts.json`` ({"scripts": ["name.py", ...]}) wins when present
    and every entry must resolve inside ``scripts/``; otherwise the
    manifest is the sorted ``scripts/`` listing (excluding bytecode).
    """
    root = Path(skill_dir)
    scripts_dir = root / "scripts"
    manifest = root / "scripts.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            names = data.get("scripts", [])
            if not isinstance(names, list):
                raise ValueError("scripts.json 'scripts' must be a list")
            out: list[dict] = []
            for name in names:
                target = (scripts_dir / str(name)).resolve()
                sroot = scripts_dir.resolve() if scripts_dir.exists() else scripts_dir
                if scripts_dir.exists() and (sroot not in target.parents and target != sroot):
                    raise ValueError(f"manifest script escapes scripts/: {name!r}")
                out.append({"name": str(name), "declared": True,
                            "exists": target.is_file() if scripts_dir.exists() else False})
            return out
        except (OSError, ValueError) as exc:
            raise ValueError(f"invalid scripts.json: {exc}") from exc
    if not scripts_dir.is_dir():
        return []
    return [{"name": p.name, "declared": False, "exists": True}
            for p in sorted(scripts_dir.iterdir())
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]


def _scan_output(output: str) -> list[str]:
    return [pat for pat in _BANNED_OUTPUT if pat in output]


def resolve_bootstrap_body(skill_dir: str | Path, command: str,
                           approval: dict | None = None) -> dict:
    """Resolve a bootstrap skill body, approval-gated.

    ``approval`` is the gate dict from ``code_agent.create_approval_gate``
    (or None). Without an approved gate, returns {"status":
    "approval_needed", "approval_id"} and the caller must create the
    gate first (the route does this). With ``approval["decision"]``
    True, runs the command and returns the capped, scanned body.
    A denied gate returns status "denied" and runs nothing.
    """
    ok, reason = validate_bootstrap_command(command)
    if not ok:
        return {"status": "rejected", "detail": reason}
    if approval is None or not approval.get("decision"):
        status = "denied" if approval is not None else "approval_needed"
        return {"status": status,
                "detail": "Bootstrap command needs approval before it runs."}
    parts = command.split()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(Path(skill_dir))}
    try:
        proc = subprocess.run(parts, capture_output=True, text=True,
                              timeout=_BOOTSTRAP_TIMEOUT_S, cwd=str(skill_dir),
                              env=env)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"status": "failed", "detail": str(exc)[:500]}
    if proc.returncode != 0:
        return {"status": "failed",
                "detail": f"bootstrap command exited {proc.returncode}: "
                          f"{(proc.stderr or '')[:500]}"}
    output = (proc.stdout or "")[:BOOTSTRAP_OUTPUT_CAP]
    banned = _scan_output(output)
    if banned:
        return {"status": "rejected",
                "detail": f"bootstrap output contains banned patterns: {banned}"}
    return {"status": "ok", "body": output,
            "truncated": len(proc.stdout or "") > BOOTSTRAP_OUTPUT_CAP}
