"""GreenContract graduated verification levels (claw-code pattern).

Binary pass/fail hides how far verification actually went. Levels
are cumulative: claiming ``package`` requires ``targeted`` passed,
``integration`` requires ``package``, and ``full`` requires all
lower levels. ``graduated_satisfied`` is the single gate the spec
pipeline's verify stage consults; a level record with ``passed=False``
never satisfies its own level, let alone a higher one.
"""
from __future__ import annotations

LEVELS = ["targeted", "package", "integration", "full"]

LEVEL_DESCRIPTIONS = {
    "targeted": "tests for the exact files/tasks changed",
    "package": "the whole package/module test suite",
    "integration": "cross-package integration tests + API routes",
    "full": "the full test suite",
}


def level_index(level: str) -> int:
    if level not in LEVELS:
        raise ValueError(f"unknown GreenContract level: {level!r} "
                         f"(expected one of {LEVELS})")
    return LEVELS.index(level)


def graduated_satisfied(level: str, verifications: list[dict]) -> bool:
    """True only when every level up to and including ``level`` has a
    passing record. ``verifications`` are {level, passed} dicts."""
    idx = level_index(level)
    passed_levels = {v.get("level") for v in (verifications or [])
                     if v.get("passed")}
    return all(lvl in passed_levels for lvl in LEVELS[:idx + 1])


def next_level(verifications: list[dict]) -> str | None:
    """First level not yet satisfied, or None when full is satisfied."""
    for lvl in LEVELS:
        if not graduated_satisfied(lvl, verifications):
            return lvl
    return None


def validate_verification_record(level: str, test_command: str,
                                 output: str, passed: bool) -> None:
    """A passing record must carry a command and a pass signal in its
    output; a failing record must not claim a clean pass. Output
    markers are checked with the same TDD pass/fail heuristics."""
    from ..spec.tdd import is_failure_output, is_pass_output
    level_index(level)
    if not (test_command or "").strip():
        raise ValueError("verification requires a test command")
    if passed and not is_pass_output(output or ""):
        raise ValueError(
            "verification claims passed but its output shows no pass signal")
    if passed and is_failure_output(output or "") and \
            not is_pass_output(output or ""):
        raise ValueError(
            "verification claims passed but its output shows a failure")
