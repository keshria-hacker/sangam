"""
security_guardrails.py — Batch 2 (security) guardrail layer.

Own-systems-only security testing inside Sangam. Every security run
names a target that must already be on the user's allowlist; the scope
check runs BEFORE any tool fires, and again at approval time (the
allowlist may have changed between creation and approval).

MUST-NOT-BUILD (refused by design, documented here so no later batch
quietly adds them):
- unrestricted autonomous exploitation;
- WAF/CAPTCHA bypass tooling;
- DDoS, RAT, phishing, brute-force / credential-stuffing, wireless
  deauth, session-hijack, backdoor / payload-injector tooling
  (see the EXCLUSIONS list in security_catalog.py);
- hunting third-party targets without allowlist proof;
- auto-install-and-run of arbitrary GitHub tools;
- agent-invented credentials (credential entry only from explicit
  user input, and this module never accepts credentials at all);
- purchases / checkouts without separate explicit confirmation
  (no purchase path exists in this module).

Models live here (not models.py) so the batch touches only its own
files; importing api_routes/security_routes.py registers these tables
with Base.metadata. RunStore mirroring uses contracts.run_store when
available; failures to mirror are swallowed — the audit table is the
durable record, RunStore is only the live plane.
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

# ---------------------------------------------------------------- models

def _now() -> datetime:
    return datetime.now(UTC)


class SecurityAllowlistTarget(Base):
    """One user-declared in-scope target: exact host or *.domain."""
    __tablename__ = "security_allowlist_targets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    host_pattern: Mapped[str] = mapped_column(String(255))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SecurityRun(Base):
    """A security run: created PENDING, executed only via approve.

    phase walks Recon -> Vuln-hunter -> Validator -> Reporter as plain
    strings on this row (no separate tabs); browser modes each need
    their own approval flag on this row.
    """
    __tablename__ = "security_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str] = mapped_column(String(512))
    scope: Mapped[str] = mapped_column(Text, default="")
    tool_class: Mapped[str] = mapped_column(String(64), default="recon")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    phase: Mapped[str] = mapped_column(String(32), default="recon")
    isolation: Mapped[str] = mapped_column(String(32), default="")
    isolation_warning: Mapped[str] = mapped_column(Text, default="")
    image_used: Mapped[str] = mapped_column(String(255), default="")
    browser_automation_approved: Mapped[bool] = mapped_column(default=False)
    browser_security_approved: Mapped[bool] = mapped_column(default=False)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SecurityFinding(Base):
    """A finding on a run. Severity is a band derived from CVSS."""
    __tablename__ = "security_findings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), ForeignKey("security_runs.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    severity: Mapped[str] = mapped_column(String(32), default="unknown")
    cvss_score: Mapped[float | None] = mapped_column(default=None)
    owasp_category: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="candidate")
    validation_verdict: Mapped[str] = mapped_column(String(32), default="")
    validation_notes: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    patch_diff: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SecurityAudit(Base):
    """Durable audit row for every security action."""
    __tablename__ = "security_audit"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(128))
    summary: Mapped[str] = mapped_column(Text, default="")
    poc_reference: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SecurityCatalogSetting(Base):
    """Per-user enable/disable override for one catalog entry."""
    __tablename__ = "security_catalog_settings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    entry_name: Mapped[str] = mapped_column(String(64), index=True)
    enabled: Mapped[bool] = mapped_column(default=True)


# ------------------------------------------------------------- scope check

def extract_host(target: str) -> str:
    """Host part of a URL or bare hostname, lowercased, port stripped."""
    raw = (target or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower()
    return host


def check_scope(target: str, allowlist: list[str]) -> bool:
    """True iff target's host matches an allowlist pattern.

    Patterns are exact hosts (``example.com``) or wildcards
    (``*.example.com`` — matches subdomains only, not the apex).
    An empty allowlist denies everything: no proof, no run.
    """
    host = extract_host(target)
    if not host:
        return False
    for pattern in allowlist:
        pat = (pattern or "").strip().lower()
        if not pat:
            continue
        if pat.startswith("*."):
            suffix = pat[1:]  # ".example.com"
            if host.endswith(suffix) and host != pat[2:]:
                return True
        elif host == pat:
            return True
    return False


# ------------------------------------------------------------ CVSS -> band

def severity_from_cvss(score: float | None) -> str:
    """CVSS v3-style band. None/invalid -> 'unknown' (never invented)."""
    if score is None:
        return "unknown"
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "unknown"
    if value <= 0:
        return "none"
    if value < 4.0:
        return "low"
    if value < 7.0:
        return "medium"
    if value < 9.0:
        return "high"
    return "critical"


# ---------------------------------------------------------------- phases

PHASES = ["recon", "vuln-hunter", "validator", "reporter"]
PHASE_LABELS = {
    "recon": "Recon",
    "vuln-hunter": "Vuln-hunter",
    "validator": "Validator",
    "reporter": "Reporter",
}
VALIDATION_VERDICTS = {"PASS", "KILL", "DOWNGRADE", "CHAIN-REQUIRED"}


def next_phase(phase: str) -> str | None:
    """Next engagement phase, or None when already at Reporter."""
    try:
        idx = PHASES.index(phase)
    except ValueError:
        return None
    return PHASES[idx + 1] if idx + 1 < len(PHASES) else None


# ------------------------------------------------------- RunStore mirror

def mirror_runstore(run_id: str, owner_id: str, title: str, state: str) -> None:
    """Best-effort mirror onto contracts.run_store (live plane only).

    The audit table is authoritative; a mirror failure must never fail
    the security operation itself, so every error is swallowed here.
    """
    try:
        from .contracts import RunState, run_store
        record = run_store.get(run_id)
        if record is None:
            record = run_store.create(kind="security", owner_id=owner_id,
                                      title=title, run_id=run_id)
        wanted = RunState(state) if state in RunState._value2member_map_ else None
        if wanted is not None and record.state != wanted:
            # PENDING -> SUCCEEDED is illegal; step through RUNNING.
            if record.state == RunState.PENDING and wanted != RunState.RUNNING:
                record.transition(RunState.RUNNING)
            record.transition(wanted)
    except Exception:
        pass


def audit_row(run_id: str, user_id: str, action: str, summary: str = "",
              poc_reference: str = "") -> SecurityAudit:
    import uuid
    return SecurityAudit(
        id=f"sa-{uuid.uuid4().hex[:12]}", run_id=run_id, user_id=user_id,
        action=action, summary=summary[:2000], poc_reference=poc_reference[:2000],
    )


# ------------------------------------------------- passive recon (v1, safe)

def _default_fetch_text(url: str, timeout: float = 10.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Sangam-Security-Recon/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — allowlisted target only
        return resp.read(65536).decode("utf-8", "replace")


def default_fetch_headers(url: str) -> dict:
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "Sangam-Security-Recon/1.0"})
    with urllib.request.urlopen(req, timeout=10.0) as resp:  # noqa: S310
        return dict(resp.headers.items())


def default_resolve_dns(host: str) -> list[str]:
    return list({socket.gethostbyname(host)})


# Injectable fetchers: tests replace these; production uses the defaults.
# Keys: "headers", "text", "dns". Each is a callable, never real network
# unless the caller leaves the default in place.
RECON_FETCHERS: dict[str, object] = {
    "headers": default_fetch_headers,
    "text": _default_fetch_text,
    "dns": default_resolve_dns,
}


def run_passive_recon(target: str) -> dict:
    """SAFE, passive-only recon: headers, robots.txt, sitemap, DNS.

    No crawling, no probing, no exploitation. Every fetcher failure is
    recorded as data (``error`` on that section), never raised — a
    failed fetch is a recon result, not a crash.
    """
    host = extract_host(target)
    base = target if "://" in target else f"https://{target}"
    out: dict = {"target": target, "host": host, "sections": {}}
    headers_fn = RECON_FETCHERS["headers"]  # type: ignore[operator]
    text_fn = RECON_FETCHERS["text"]  # type: ignore[operator]
    dns_fn = RECON_FETCHERS["dns"]  # type: ignore[operator]
    for name, fn in (("headers", lambda: headers_fn(base)),
                     ("robots.txt", lambda: text_fn(f"{base.rstrip('/')}/robots.txt")),
                     ("sitemap.xml", lambda: text_fn(f"{base.rstrip('/')}/sitemap.xml"))):
        try:
            out["sections"][name] = {"ok": True, "data": fn()}
        except Exception as exc:  # noqa: BLE001 — recon failure is data
            out["sections"][name] = {"ok": False, "error": str(exc)[:500]}
    try:
        out["sections"]["dns"] = {"ok": True, "data": dns_fn(host) if host else []}
    except Exception as exc:  # noqa: BLE001
        out["sections"]["dns"] = {"ok": False, "error": str(exc)[:500]}
    return out


# ------------------------------------------------------ execution isolation

WORKSPACE_FALLBACK_WARNING = (
    "Docker is not available on this machine: this run executed under "
    "workspace confinement only (cwd pinned to the run workspace, "
    "scrubbed environment, command timeout). It did NOT "
    "run in an isolated container. Install Docker for container isolation."
)
DOCKER_IMAGE = "sangam/security-runner:latest"


@dataclass
class IsolationResult:
    isolation: str  # "docker" | "workspace-fallback"
    warning: str = ""
    image_used: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None


def docker_available() -> bool:
    return shutil.which("docker") is not None


def run_isolated_command(command: list[str], workspace_dir: str | Path,
                         timeout: float = 120.0,
                         docker_present: bool | None = None) -> IsolationResult:
    """Run a tool command under the best available isolation.

    Docker path: ephemeral container (``--rm``), no host mounts except
    an optional read-only workspace mount, image recorded on the run.
    Network is NOT cut off (tools must reach the allowlisted target);
    the guardrail is the scope check that runs before invocation.
    Fallback path: subprocess pinned to the workspace dir with a
    scrubbed environment — and the warning is ALWAYS recorded, never
    silent. ``docker_present`` is injectable so tests can force either
    backend without a real Docker daemon.
    """
    ws = Path(workspace_dir)
    ws.mkdir(parents=True, exist_ok=True)
    present = docker_present if docker_present is not None else docker_available()
    if present:
        docker_cmd = ["docker", "run", "--rm",
                      "-v", f"{ws}:/workspace:ro", DOCKER_IMAGE] + list(command)
        try:
            proc = subprocess.run(docker_cmd, capture_output=True, text=True,
                                  timeout=timeout)
            return IsolationResult(isolation="docker", image_used=DOCKER_IMAGE,
                                   stdout=proc.stdout[-4000:], stderr=proc.stderr[-2000:],
                                   returncode=proc.returncode)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return IsolationResult(isolation="docker", image_used=DOCKER_IMAGE,
                                   stderr=str(exc)[:2000], returncode=None)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(ws)}
    try:
        proc = subprocess.run(list(command), capture_output=True, text=True,
                              timeout=timeout, cwd=str(ws), env=env)
        return IsolationResult(isolation="workspace-fallback",
                               warning=WORKSPACE_FALLBACK_WARNING,
                               stdout=proc.stdout[-4000:], stderr=proc.stderr[-2000:],
                               returncode=proc.returncode)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return IsolationResult(isolation="workspace-fallback",
                               warning=WORKSPACE_FALLBACK_WARNING,
                               stderr=str(exc)[:2000], returncode=None)
