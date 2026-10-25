"""Circuit breaker for runaway agents (server-side, never a browser timer).

Three trip conditions, all evaluated in the executor after every step:

* error storm — ``max_consecutive_errors`` failed steps in a row;
* velocity — ``max_steps_per_minute`` steps started inside a 60s window
  (a loop spinning through cheap steps trips even without errors);
* no progress — ``max_no_progress`` consecutive steps whose output is
  empty or byte-identical to the previous step's output.

A trip stops the run immediately; remaining steps stay pending so a
human can inspect, fix, and resume. Thresholds are per-task config
overrides falling back to the module defaults (also exposed as settings
keys in MANIFEST.md for the Settings centre).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

DEFAULT_MAX_CONSECUTIVE_ERRORS = 5
DEFAULT_MAX_STEPS_PER_MINUTE = 30
DEFAULT_MAX_NO_PROGRESS = 3


@dataclass
class CircuitBreaker:
    max_consecutive_errors: int = DEFAULT_MAX_CONSECUTIVE_ERRORS
    max_steps_per_minute: int = DEFAULT_MAX_STEPS_PER_MINUTE
    max_no_progress: int = DEFAULT_MAX_NO_PROGRESS
    consecutive_errors: int = 0
    consecutive_no_progress: int = 0
    step_starts: list[float] = field(default_factory=list)
    _last_output: str | None = None
    tripped_reason: str | None = None

    @property
    def tripped(self) -> bool:
        return self.tripped_reason is not None

    def record_step_start(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self.step_starts.append(now)
        self.step_starts = [t for t in self.step_starts if now - t < 60.0]
        if len(self.step_starts) > self.max_steps_per_minute:
            self.tripped_reason = (
                f"velocity: {len(self.step_starts)} steps started within 60s "
                f"(limit {self.max_steps_per_minute})")

    def record_success(self, output: object) -> None:
        self.consecutive_errors = 0
        text = "" if output is None else str(output)
        if not text.strip() or text == self._last_output:
            self.consecutive_no_progress += 1
        else:
            self.consecutive_no_progress = 0
        self._last_output = text
        if self.consecutive_no_progress >= self.max_no_progress:
            self.tripped_reason = (
                f"no progress: {self.consecutive_no_progress} consecutive "
                "steps produced empty or unchanged output")

    def record_error(self) -> None:
        self.consecutive_errors += 1
        self.consecutive_no_progress = 0
        if self.consecutive_errors >= self.max_consecutive_errors:
            self.tripped_reason = (
                f"error storm: {self.consecutive_errors} consecutive step failures "
                f"(limit {self.max_consecutive_errors})")
