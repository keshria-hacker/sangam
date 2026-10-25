"""agent_runtime/drivers.py — supervised external-agent drivers (Batch 10).

PersonalJarvis dodaios, Sangam-native: a ``RuntimeDriver`` protocol
that lets Sangam SUPERVISE an external coding agent (Claude / Codex /
ACP-style CLIs) as a managed subprocess — detect, start, health-check,
kill, log-tail — under the same approval policy as native runs.

What this is NOT:

* It does not pretend external agents are native tools, and it does
  not execute them from an API endpoint: spawning an arbitrary command
  from an HTTP request would be unrestricted code execution. The API
  exposes detection only (is the binary present?); spawning stays a
  library call the host operator makes deliberately.
* Voice / wake-word / pet UI from PersonalJarvis are explicitly out of
  scope (not agent runtime).
"""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


KNOWN_RUNTIMES = ("claude", "codex", "acp")


def detect_runtime(name: str) -> dict:
    """Detect one external runtime binary on PATH. No execution."""
    binary = shutil.which(name)
    return {"name": name, "available": binary is not None,
            "binary": binary or "",
            "supervised": True,
            "note": ("Binary present; spawning is host-operator initiated, "
                     "never from an API request." if binary else
                     "Binary not found on PATH; this runtime cannot be supervised here.")}


def detect_all() -> list[dict]:
    return [detect_runtime(name) for name in KNOWN_RUNTIMES]


class RuntimeDriver(Protocol):
    """Protocol for a supervised external agent (dodaios AgentRuntimeDriver)."""

    def detect(self) -> dict: ...
    def start(self, command: list[str]) -> dict: ...
    def status(self) -> dict: ...
    def health(self) -> dict: ...
    def log_tail(self, lines: int = 50) -> str: ...
    def kill(self) -> dict: ...


@dataclass
class LocalCommandDriver:
    """Subprocess driver: spawn, poll health, tail logs, kill.

    ``command`` is argv (never shell). The driver records stdout/stderr
    tails only; it never streams secrets (callers must not pass tokens
    as argv — use env files / credential stores instead).
    """

    name: str = "external"
    _proc: Any = field(default=None, repr=False)
    _started_at: float = 0.0
    _command: list[str] = field(default_factory=list)

    def detect(self) -> dict:
        return detect_runtime(self.name)

    def start(self, command: list[str]) -> dict:
        if self._proc is not None and self._proc.poll() is None:
            return {"ok": False, "error": "driver already running"}
        if not command:
            raise ValueError("driver command must not be empty")
        try:
            self._proc = subprocess.Popen(
                list(command), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        self._started_at = time.time()
        self._command = list(command)
        return {"ok": True, "name": self.name, "pid": self._proc.pid,
                "command": self._command}

    def status(self) -> dict:
        if self._proc is None:
            return {"running": False, "pid": None, "returncode": None}
        return {"running": self._proc.poll() is None,
                "pid": self._proc.pid, "returncode": self._proc.poll(),
                "uptime_s": round(time.time() - self._started_at, 1)
                if self._started_at else 0.0}

    def health(self) -> dict:
        """Health = process alive (rollback-on-failure lives with caller).

        A dead process with a nonzero returncode is 'failed', not
        'healthy'; a clean exit is 'completed'. No fake 'ok' for a
        process that never started.
        """
        st = self.status()
        if st["pid"] is None:
            return {"healthy": False, "state": "not-started"}
        if st["running"]:
            return {"healthy": True, "state": "running"}
        if st["returncode"] == 0:
            return {"healthy": True, "state": "completed"}
        return {"healthy": False, "state": "failed",
                "returncode": st["returncode"]}

    def log_tail(self, lines: int = 50) -> str:
        # Popen with PIPE buffers; a tail is only meaningful after the
        # process exits (communicate drains it). While running, report
        # honestly instead of returning a partial buffer.
        if self._proc is None:
            return ""
        if self._proc.poll() is None:
            return "(process still running; log tail available after exit)"
        try:
            out, _ = self._proc.communicate(timeout=5)
        except (subprocess.TimeoutExpired, ValueError):
            return ""
        return "\n".join((out or "").splitlines()[-max(1, lines):])

    def kill(self) -> dict:
        if self._proc is None:
            return {"ok": False, "error": "driver never started"}
        if self._proc.poll() is None:
            self._proc.kill()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            return {"ok": True, "killed": True, "pid": self._proc.pid}
        return {"ok": True, "killed": False,
                "detail": "process already exited",
                "returncode": self._proc.poll()}
