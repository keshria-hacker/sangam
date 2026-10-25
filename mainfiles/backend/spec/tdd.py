"""TDD enforcement as code, not a prompt sentence.

A task's TDD evidence is a pair of REAL test outputs for the SAME
test command: a RED run (the test fails before the implementation)
and a GREEN run (it passes after). ``validate_tdd_evidence`` rejects
evidence that does not satisfy both halves, so an implement stage
gated on this cannot be satisfied by pasting a single green run or
by claiming TDD in prose.

Failure markers are deliberately broad across runners (pytest,
unittest, Jest, Go test, cargo test): any of FAILED / failed /
AssertionError / panic / ``not ok`` counts as RED, provided the
output does NOT also claim a clean pass. Pass markers require an
explicit pass signal (``passed``, ``ok``, ``PASS``, ``1 passed``,
``test result: ok``) and no failure marker. Outputs are capped at
4000 chars at storage time by the route layer (same cap as the old
task-run ledger); validation itself is length-agnostic.
"""
from __future__ import annotations

import re

_FAILURE_PATTERNS = (
    r"\bFAILED\b", r"\bfailed\b", r"AssertionError", r"\bpanicked\b",
    r"^not ok\b", r"test result: FAILED", r"\d+ failed",
)
_PASS_PATTERNS = (
    r"\bpassed\b", r"\bPASS\b", r"\bok\b", r"test result: ok",
    r"\d+ passed",
)
_FAILURE_RES = [re.compile(p, re.IGNORECASE) for p in _FAILURE_PATTERNS]
_PASS_RES = [re.compile(p) for p in _PASS_PATTERNS]


def is_failure_output(output: str) -> bool:
    text = output or ""
    if not text.strip():
        return False
    if any(p.search(text) for p in _PASS_RES) and \
            not any(p.search(text) for p in _FAILURE_RES):
        return False
    # A mixed run (e.g. "1 failed, 2 passed") is still a failure:
    # RED only needs the test under development to fail.
    return any(p.search(text) for p in _FAILURE_RES)


def is_pass_output(output: str) -> bool:
    text = output or ""
    if not text.strip():
        return False
    if any(p.search(text) for p in _FAILURE_RES):
        return False
    return any(p.search(text) for p in _PASS_RES)


def validate_tdd_evidence(test_command: str, red_output: str,
                          green_output: str) -> dict:
    """Raise ValueError unless RED+GREEN evidence is real for one command.

    Returns a summary dict (red_ok, green_ok) for storage.
    """
    if not (test_command or "").strip():
        raise ValueError("TDD evidence requires a test command")
    if not is_failure_output(red_output or ""):
        raise ValueError(
            "TDD RED evidence rejected: red output shows no test failure "
            "(expected FAILED/failed/AssertionError/panic/not ok)")
    if not is_pass_output(green_output or ""):
        raise ValueError(
            "TDD GREEN evidence rejected: green output shows no clean pass "
            "or still contains a failure marker")
    return {"test_command": test_command.strip(),
            "red_ok": True, "green_ok": True}
