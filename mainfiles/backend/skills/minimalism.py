"""
skills/minimalism.py — ponytail minimalism ladder, shortcut debt ledger,
and reviewer discipline (deep-read Wave 2).

Ladder (a mode / prompt discipline for the engineering path, NOT a
refusal mechanism): before writing new code, decide in this order —
1. need? (is it needed at all) 2. reuse (existing code) 3. stdlib /
platform 4. installed dependency 5. one-liner 6. minimum new code.
Never cut validation, security, or accessibility for leanness, and new
logic ships with one test. ``ultra`` pushback is a QUESTION, never a
refusal: a confirmed request is still built.

Shortcut ledger: ``shortcut: <ceiling>, <upgrade trigger>`` comments
in code are the debt ledger. ``scan_shortcuts`` is READ-ONLY (grep).
The ledger is persisted ONLY on explicit request
(``persist_shortcut_ledger(..., explicit=True)``); anything else raises.
A shortcut with no trigger (or a literal ``no-trigger``) is flagged as
rot, not silently accepted.

Reviewer discipline: findings are reported in check order
correct -> safe -> load -> tested -> fast -> lean, each with
What/Problem/Fix/If-we-skip-it, plus Verdict / Lean / Not-checked.
Reuse %: Sangam's AST code graph (code_graph.build_graph) exposes
symbol/call edges but NO per-diff reuse metric, so
``reuse_pct_for_diff`` honestly returns None with the reason instead
of a guessed percentage. Callers must print the reason, not a number.
"""
from __future__ import annotations

import re
from pathlib import Path

LADDER_ORDER = ["need", "reuse", "stdlib", "installed-dep", "one-liner",
                "minimum-code"]
NON_NEGOTIABLES = ["validation", "security", "accessibility"]

_LADDER_TEXT = """Minimalism ladder ({mode}):
Decide in this order, and stop at the first rung that satisfies the need:
1. Need? — is this needed at all? If not, do not build it.
2. Reuse — use existing code in this codebase before writing new code.
3. Stdlib / platform — prefer the standard library / platform feature.
4. Installed dependency — use a dependency already installed.
5. One-liner — a single clear expression beats a helper.
6. Minimum code — write the smallest code that satisfies the need.
Never cut validation, security, or accessibility for leanness.
New logic ships with one test.
{ultra_note}"""

REVIEW_CHECK_ORDER = ["correct", "safe", "load", "tested", "fast", "lean"]
REVIEW_SEVERITIES = ("Must", "Should", "Nice")


def ladder_system_prompt(mode: str = "lite") -> str:
    """Prompt discipline text for the engineering path.

    Modes: lite (apply the ladder), full (apply + justify each new
    dependency), ultra (apply + push back with a question when the
    ladder says a request is unneeded — never refuse a confirmed ask).
    """
    mode = (mode or "lite").lower()
    if mode not in ("lite", "full", "ultra"):
        raise ValueError(f"Unknown ladder mode: {mode!r} (lite/full/ultra)")
    ultra_note = ""
    if mode == "full":
        ultra_note = ("Every new dependency must be justified in one line: "
                      "why reuse/stdlib cannot do it.")
    elif mode == "ultra":
        ultra_note = ("Ultra pushback: when the ladder says the request is "
                      "unneeded, ask ONE question before building — but if "
                      "the user confirms, build it. Pushback is a question, "
                      "never a refusal.")
    return _LADDER_TEXT.format(mode=mode, ultra_note=ultra_note)


_SHORTCUT_RE = re.compile(
    r"shortcut:\s*(?P<ceiling>[^,]+?)\s*,\s*(?P<trigger>.*)$")


def scan_shortcuts(workspace_root: Path) -> dict:
    """Read-only grep of ``shortcut:`` debt markers.

    Returns {shortcuts: [{file, line, ceiling, trigger, rot}], count,
    rot_count}. ``rot`` is True when the trigger is empty or the literal
    ``no-trigger`` — debt with no upgrade path.
    """
    root = Path(workspace_root)
    found: list[dict] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, start=1):
            match = _SHORTCUT_RE.search(line)
            if not match:
                continue
            trigger = match.group("trigger").strip()
            found.append({
                "file": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
                "line": lineno,
                "ceiling": match.group("ceiling").strip(),
                "trigger": trigger,
                "rot": (not trigger) or trigger.lower() == "no-trigger",
            })
    return {"shortcuts": found, "count": len(found),
            "rot_count": sum(1 for s in found if s["rot"])}


def persist_shortcut_ledger(workspace_root: Path, output_path: Path,
                            explicit: bool = False) -> dict:
    """Persist the shortcut ledger — ONLY on explicit request.

    Without explicit=True this raises ValueError and writes nothing:
    scanning is free, persisting is a deliberate act.
    """
    if not explicit:
        raise ValueError("Shortcut ledger is persisted only on explicit "
                         "request (pass explicit=True)")
    report = scan_shortcuts(workspace_root)
    lines = ["# Shortcut debt ledger (generated on explicit request)",
             ""]
    for item in report["shortcuts"]:
        flag = " [ROT: no upgrade trigger]" if item["rot"] else ""
        lines.append(f"- {item['file']}:{item['line']} — ceiling: "
                     f"{item['ceiling']}; upgrade when: {item['trigger']}{flag}")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {**report, "ledger_path": str(output_path)}


def format_review_finding(severity: str, check: str, what: str,
                          problem: str, fix: str, if_we_skip_it: str) -> dict:
    """One reviewer finding in ponytail format.

    severity: Must / Should / Nice. check: one of REVIEW_CHECK_ORDER.
    Concrete case or no finding: callers must not emit vague findings.
    """
    if severity not in REVIEW_SEVERITIES:
        raise ValueError(f"Severity must be one of {REVIEW_SEVERITIES}")
    if check not in REVIEW_CHECK_ORDER:
        raise ValueError(f"Check must be one of {REVIEW_CHECK_ORDER}")
    return {"severity": severity, "check": check, "what": what,
            "problem": problem, "fix": fix, "if_we_skip_it": if_we_skip_it}


def format_review_verdict(findings: list[dict], lean_notes: list[str] | None = None,
                          not_checked: list[str] | None = None) -> str:
    """Render Verdict / Lean / Not-checked for a review over a real diff."""
    musts = [f for f in findings if f.get("severity") == "Must"]
    verdict = ("CHANGES REQUIRED" if musts else
               "APPROVED" if not findings else "APPROVED WITH NOTES")
    lines = [f"Verdict: {verdict}"]
    for finding in findings:
        lines.append(f"- [{finding['severity']}] ({finding['check']}) "
                     f"{finding['what']}: {finding['problem']} "
                     f"Fix: {finding['fix']} "
                     f"If we skip it: {finding['if_we_skip_it']}")
    lines.append("Lean: " + ("; ".join(lean_notes) if lean_notes else "none noted"))
    lines.append("Not checked: " + (", ".join(not_checked) if not_checked else "none"))
    lines.append("Reuse: not measured — the AST code graph exposes symbol/call "
                 "edges but no per-diff reuse metric; no percentage is claimed.")
    return "\n".join(lines)


def reuse_pct_for_diff(diff_text: str, graph: dict | None = None) -> dict:
    """Reuse % for a diff — honestly unavailable.

    The AST graph (code_graph.build_graph) can list symbols and call
    edges for a tree, but it has no baseline-vs-diff comparison and no
    per-diff reuse API, so any percentage would be a guess. This
    returns reuse_pct=None plus the reason; callers surface the reason
    and skip the number. ``diff_text``/``graph`` are accepted so the
    signature stays stable if a real metric lands later.
    """
    del diff_text, graph  # accepted for signature stability; not guessed from
    return {"reuse_pct": None,
            "reason": "AST code graph has no per-diff reuse metric "
                      "(symbols/edges only, no baseline comparison); "
                      "percentage skipped rather than estimated"}
