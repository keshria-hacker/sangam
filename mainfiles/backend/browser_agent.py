"""
browser_agent.py — Batch 2 browser agent (Python wrapper).

TWO separately-gated modes, never one merged tool:
- mode="automation": QA / forms / extraction on allowlisted own sites
  plus public, non-authenticated research pages.
- mode="security-test": client-side probing of the user's own
  allowlisted app.

Each mode needs its own approval flag on the security run (see
security_guardrails.SecurityRun); this wrapper only validates the
mode string — the route enforces the per-mode flag.

The driver is browser_driver.mjs (Node + playwright-core, isolated
profile dir under the workspace, never the user's daily profile).
If Node, the driver file, or the Playwright engine is unavailable,
run_actions raises BrowserDriverUnavailable and the route returns
503 — it never fabricates results. Tests inject ``driver_runner``
and never launch a real browser.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

MODES = ("automation", "security-test")
ACTIONS = ("navigate", "click", "type", "extract", "screenshot")

DRIVER_TIMEOUT_SECONDS = 120.0


class BrowserDriverUnavailable(RuntimeError):
    """Node, the driver script, or the Playwright engine is missing."""


class BrowserActionError(ValueError):
    """An action list failed validation before anything ran."""


def validate_actions(actions: object) -> list[dict]:
    """Validate an action list. Raises BrowserActionError on bad input."""
    if not isinstance(actions, list) or not actions:
        raise BrowserActionError("actions must be a non-empty list")
    if len(actions) > 50:
        raise BrowserActionError("at most 50 actions per browser run")
    clean: list[dict] = []
    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            raise BrowserActionError(f"action {i} is not an object")
        kind = action.get("action")
        if kind not in ACTIONS:
            raise BrowserActionError(f"action {i}: unknown action {kind!r}")
        if kind in ("navigate",) and not action.get("url"):
            raise BrowserActionError(f"action {i}: navigate needs url")
        if kind in ("click", "type") and not action.get("selector"):
            raise BrowserActionError(f"action {i}: {kind} needs selector")
        if kind == "type" and "text" not in action:
            raise BrowserActionError(f"action {i}: type needs text")
        clean.append({k: v for k, v in action.items()
                      if k in ("action", "url", "selector", "text", "name")})
    return clean


@dataclass
class BrowserResult:
    mode: str
    results: list[dict]
    screenshot_paths: list[str]


def default_driver_path() -> Path:
    return Path(__file__).resolve().parent / "browser_driver.mjs"


def _default_runner(payload: dict, driver: Path, timeout: float) -> dict:
    if not driver.exists():
        raise BrowserDriverUnavailable(f"Browser driver not found: {driver}")
    node = "node"
    try:
        proc = subprocess.run(
            [node, str(driver)], input=json.dumps(payload), capture_output=True,
            text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise BrowserDriverUnavailable("Node.js is not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise BrowserDriverUnavailable(f"Browser driver timed out after {timeout}s") from exc
    try:
        parsed = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
    except (json.JSONDecodeError, IndexError) as exc:
        raise BrowserDriverUnavailable(f"Browser driver returned unparsable output: {proc.stderr[:500]}") from exc
    if proc.returncode != 0 or parsed.get("error"):
        raise BrowserDriverUnavailable(
            parsed.get("error") or f"Browser driver failed (exit {proc.returncode}): {proc.stderr[:500]}")
    return parsed


def run_browser_actions(mode: str, actions: list[dict], profile_dir: str | Path,
                        driver_runner: Callable[[dict, Path, float], dict] | None = None,
                        driver: Path | None = None,
                        timeout: float = DRIVER_TIMEOUT_SECONDS) -> BrowserResult:
    """Run a validated action list through the driver.

    ``driver_runner`` is the injection point for tests (a fake driver);
    production always uses the real Node driver. Every caller must log
    the returned actions + screenshot paths to the audit table.
    """
    if mode not in MODES:
        raise BrowserActionError(f"Unknown browser mode {mode!r}; expected one of {MODES}")
    clean = validate_actions(actions)
    profile = Path(profile_dir)
    profile.mkdir(parents=True, exist_ok=True)
    payload = {"actions": clean, "profileDir": str(profile)}
    runner = driver_runner or _default_runner
    parsed = runner(payload, driver or default_driver_path(), timeout)
    results = parsed.get("results", [])
    screenshots = [r["screenshot"] for r in results
                   if isinstance(r, dict) and r.get("screenshot")]
    return BrowserResult(mode=mode, results=results, screenshot_paths=screenshots)
