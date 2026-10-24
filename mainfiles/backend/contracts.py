"""Phase 0 shared contracts for Sangam's all-in-one program.

This module is intentionally additive and dependency-light: it introduces
the contracts the plan calls for — error envelope, pagination, correlation
IDs, run/job state machine, event envelope, capability manifest, provider
telemetry, and artifact storage — without changing any existing route's
response shape. Existing routes adopt these contracts one at a time
(see runs_routes pagination, the 500 handler in main.py, and the chat
stream's USAGE telemetry); new capabilities must use them from day one.

Rules enforced here:
- Every error carries a machine-readable ``code`` and a correlation ID.
  Raw error text is redacted before it is ever stored or returned:
  bearer tokens, ``sk-`` style keys, and long secret-looking tokens
  become ``[REDACTED]``.
- Every list response can carry a ``pagination`` block; callers that
  only read the items list keep working.
- Every long operation is a RunRecord with a guarded state machine:
  pending -> running -> succeeded | failed | cancelled. Terminal
  states are final; illegal transitions raise.
- Every capability declares its I/O schema, permissions, side effects,
  resource limits, and approval requirement before it runs.
- Every provider call that is recorded carries provider/model, latency,
  tokens, and a cost estimate; failures record a category, never a
  secret.
- Every artifact goes through ArtifactStore, which rejects path
  traversal in artifact IDs and never serves a path outside its root.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

__all__ = [
    "PaginationParams",
    "paginate",
    "redact_error_message",
    "error_envelope",
    "correlation_id_for",
    "RunState",
    "RunRecord",
    "RunStore",
    "run_store",
    "run_event",
    "CapabilityKind",
    "CapabilityManifest",
    "capability_manifest_from_extension",
    "ProviderTelemetryRecord",
    "TelemetryLedger",
    "telemetry_ledger",
    "ArtifactStore",
    "LocalArtifactStore",
]

# ---------------------------------------------------------------- errors

_SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[^\s]+"),
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+"),
]


def redact_error_message(message: str) -> str:
    """Strip secret-looking material from an error message."""
    text = message or ""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]", text)
    return text


def error_envelope(code: str, message: str, correlation_id: str | None = None,
                   details: dict[str, Any] | None = None) -> dict[str, Any]:
    """One error shape for the whole API.

    Kept separate from FastAPI's ``{"detail": ...}`` body so existing
    routes can adopt it without breaking clients that read ``detail``:
    adopters return both (see main.py's 500 handler).
    """
    return {
        "error": {
            "code": code,
            "message": redact_error_message(message),
            "details": details or {},
        },
        "correlation_id": correlation_id,
    }


def correlation_id_for(request: Any) -> str:
    """Correlation ID for a request: the X-Request-ID already set by
    RequestIDMiddleware, or a fresh short id if middleware did not run
    (e.g. unit tests calling handlers directly)."""
    state = getattr(request, "state", None)
    existing = getattr(state, "request_id", None) if state is not None else None
    return existing or uuid.uuid4().hex[:12]


# ------------------------------------------------------------ pagination

class PaginationParams(BaseModel):
    """Query pagination with sane, enforced bounds."""

    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)

    @field_validator("limit", mode="before")
    @classmethod
    def _clamp_limit(cls, value: Any) -> int:
        try:
            return max(1, min(int(value), 200))
        except (TypeError, ValueError):
            return 50


def paginate(items: list[Any], total: int, params: PaginationParams) -> dict[str, Any]:
    """Wrap a page of items with a pagination block (additive: callers
    that only read ``items`` are unaffected)."""
    end = params.offset + len(items)
    return {
        "items": items,
        "pagination": {
            "total": total,
            "limit": params.limit,
            "offset": params.offset,
            "has_more": end < total,
        },
    }


# ------------------------------------------------------------ runs / jobs

class RunState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (RunState.SUCCEEDED, RunState.FAILED, RunState.CANCELLED)


_ALLOWED_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.PENDING: {RunState.RUNNING, RunState.CANCELLED},
    RunState.RUNNING: {RunState.SUCCEEDED, RunState.FAILED, RunState.CANCELLED},
    RunState.SUCCEEDED: set(),
    RunState.FAILED: set(),
    RunState.CANCELLED: set(),
}


@dataclass
class RunRecord:
    run_id: str
    kind: str  # 'agent' | 'code-agent' | 'team' | 'workflow' | 'media' | ...
    owner_id: str
    title: str = ""
    state: RunState = RunState.PENDING
    progress: float = 0.0  # 0.0 .. 1.0
    tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    sequence: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def transition(self, new_state: RunState, *, error: str | None = None,
                   progress: float | None = None) -> None:
        if new_state not in _ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"Illegal run transition {self.state} -> {new_state}")
        self.state = new_state
        if error is not None:
            self.error = redact_error_message(error)
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        self.updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "owner_id": self.owner_id,
            "title": self.title,
            "state": self.state.value,
            "progress": self.progress,
            "tokens": self.tokens,
            "cost_usd": self.cost_usd,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class RunStore:
    """Thread-safe in-memory run plane for live progress.

    Durable history still lives in the AgentRun DB table (runs_routes);
    this store is the live plane: progress, cancellation, and events
    for runs in flight. Completed runs are mirrored here by
    runs_routes.record_run so live and durable views agree on id,
    kind, state, tokens, and cost.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, RunRecord] = {}

    def create(self, kind: str, owner_id: str, title: str = "",
               run_id: str | None = None) -> RunRecord:
        record = RunRecord(run_id=run_id or f"run-{uuid.uuid4().hex[:12]}",
                           kind=kind, owner_id=owner_id, title=title)
        with self._lock:
            self._runs[record.run_id] = record
        return record

    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def list_for_owner(self, owner_id: str) -> list[RunRecord]:
        with self._lock:
            return [r for r in self._runs.values() if r.owner_id == owner_id]

    def transition(self, run_id: str, new_state: RunState, **kwargs: Any) -> RunRecord:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                raise KeyError(f"Unknown run {run_id}")
            record.transition(new_state, **kwargs)
            return record


# One process-wide live plane; tests construct their own RunStore.
run_store = RunStore()


def run_event(record: RunRecord, event_type: str,
              data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Typed progress event envelope for a run (SSE payload shape)."""
    record.sequence += 1
    return {
        "run_id": record.run_id,
        "type": event_type,
        "sequence": record.sequence,
        "state": record.state.value,
        "progress": record.progress,
        "data": data or {},
    }


# ------------------------------------------------- capability manifests

class CapabilityKind(StrEnum):
    SKILL = "skill"
    TOOL = "tool"
    MCP_SERVER = "mcp_server"
    AGENT = "agent"
    WORKFLOW_NODE = "workflow_node"


class CapabilityManifest(BaseModel):
    """The contract every capability must declare before it runs."""

    name: str = Field(min_length=1, max_length=128)
    version: str = Field(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
    kind: CapabilityKind
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)
    resource_limits: dict[str, Any] = Field(default_factory=dict)
    approval_required: bool = False
    enabled_by_default: bool = True


def capability_manifest_from_extension(manifest: Any) -> CapabilityManifest:
    """Adapt an existing ExtensionManifest to the Phase 0 capability
    contract. Extension kinds map 1:1 except provider/capability, which
    have no capability-kind equivalent and are rejected rather than
    silently mislabelled."""
    from .extensions.manifest import ExtensionKind

    kind_map = {
        ExtensionKind.TOOL: CapabilityKind.TOOL,
        ExtensionKind.SKILL: CapabilityKind.SKILL,
        ExtensionKind.MCP_SERVER: CapabilityKind.MCP_SERVER,
    }
    kind = kind_map.get(manifest.kind)
    if kind is None:
        raise ValueError(f"Extension kind {manifest.kind!r} has no capability equivalent")
    return CapabilityManifest(
        name=manifest.name,
        version=manifest.version,
        kind=kind,
        description=manifest.description or "",
        input_schema={},
        output_schema={},
        permissions=[],
        side_effects=[],
        resource_limits={},
        approval_required=False,
        enabled_by_default=manifest.enabled_by_default,
    )


# --------------------------------------------------- provider telemetry

@dataclass
class ProviderTelemetryRecord:
    provider: str
    model: str | None
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    success: bool = True
    error_category: str | None = None
    correlation_id: str | None = None
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class TelemetryLedger:
    """In-memory provider telemetry: latency, tokens, cost, failures.

    Cost is computed only when the caller supplies prices (per 1k
    tokens); without prices the record still carries tokens and
    latency, and cost stays 0.0 rather than inventing a price.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[ProviderTelemetryRecord] = []

    def record(self, provider: str, model: str | None, latency_ms: float,
               input_tokens: int = 0, output_tokens: int = 0,
               input_price_per_1k: float = 0.0, output_price_per_1k: float = 0.0,
               success: bool = True, error: str | None = None,
               correlation_id: str | None = None) -> ProviderTelemetryRecord:
        record = ProviderTelemetryRecord(
            provider=provider, model=model, latency_ms=latency_ms,
            input_tokens=input_tokens, output_tokens=output_tokens,
            cost_usd=(input_tokens / 1000.0) * input_price_per_1k
            + (output_tokens / 1000.0) * output_price_per_1k,
            success=success,
            error_category=redact_error_message(error) if error else None,
            correlation_id=correlation_id,
        )
        with self._lock:
            self._records.append(record)
        return record

    def totals(self, provider: str | None = None) -> dict[str, Any]:
        with self._lock:
            records = [r for r in self._records if provider is None or r.provider == provider]
        return {
            "calls": len(records),
            "failures": sum(1 for r in records if not r.success),
            "input_tokens": sum(r.input_tokens for r in records),
            "output_tokens": sum(r.output_tokens for r in records),
            "cost_usd": round(sum(r.cost_usd for r in records), 6),
            "avg_latency_ms": round(
                sum(r.latency_ms for r in records) / len(records), 2) if records else 0.0,
        }


telemetry_ledger = TelemetryLedger()


# ------------------------------------------------------- artifact store

class ArtifactStore:
    """Storage abstraction for artifacts. Local store now, S3-compatible
    later — callers use save/get/delete/metadata and never touch paths."""

    def save(self, artifact_id: str, data: bytes, content_type: str,
             owner_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def get(self, artifact_id: str) -> bytes | None:
        raise NotImplementedError

    def delete(self, artifact_id: str) -> bool:
        raise NotImplementedError

    def metadata(self, artifact_id: str) -> dict[str, Any] | None:
        raise NotImplementedError


_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class LocalArtifactStore(ArtifactStore):
    """Filesystem ArtifactStore rooted at one directory."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, artifact_id: str) -> Path:
        if not _ARTIFACT_ID_RE.match(artifact_id) or ".." in artifact_id:
            raise ValueError(f"Invalid artifact id {artifact_id!r}")
        path = (self.root / artifact_id).resolve()
        if path.parent != self.root.resolve():
            raise ValueError(f"Artifact id escapes store root: {artifact_id!r}")
        return path

    def save(self, artifact_id: str, data: bytes, content_type: str,
             owner_id: str) -> dict[str, Any]:
        path = self._path(artifact_id)
        path.write_bytes(data)
        return {"artifact_id": artifact_id, "content_type": content_type,
                "owner_id": owner_id, "size_bytes": len(data)}

    def get(self, artifact_id: str) -> bytes | None:
        try:
            path = self._path(artifact_id)
        except ValueError:
            return None
        return path.read_bytes() if path.exists() else None

    def delete(self, artifact_id: str) -> bool:
        try:
            path = self._path(artifact_id)
        except ValueError:
            return False
        if path.exists():
            path.unlink()
            return True
        return False

    def metadata(self, artifact_id: str) -> dict[str, Any] | None:
        try:
            path = self._path(artifact_id)
        except ValueError:
            return None
        if not path.exists():
            return None
        return {"artifact_id": artifact_id, "size_bytes": path.stat().st_size}


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


# --------------------------------------------- signed artifact downloads
# Phase 1: a signed URL lets an artifact be downloaded through a single
# bearer token (no session needed) for a short window. The token binds
# artifact id + owner id + expiry and is HMAC-signed; verification is
# constant-time and rejects expired or tampered tokens. The signing
# secret is MASTER_KEY when set, otherwise a process-local secret
# (tokens then invalidate on restart — acceptable for 15-minute URLs).

import base64
import hashlib
import hmac as _hmac
import json as _json
import secrets as _secrets

_FALLBACK_SIGNING_SECRET = _secrets.token_hex(32)


def signing_secret(master_key: str | None) -> str:
    return master_key or _FALLBACK_SIGNING_SECRET


def sign_artifact_token(artifact_id: str, owner_id: str, secret: str,
                        expires_in_seconds: int = 900) -> str:
    payload = {
        "artifact_id": artifact_id,
        "owner_id": owner_id,
        "exp": int(time.time()) + int(expires_in_seconds),
    }
    body = base64.urlsafe_b64encode(_json.dumps(payload, sort_keys=True).encode()).decode().rstrip("=")
    sig = _hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_artifact_token(token: str, secret: str) -> dict[str, Any] | None:
    """Return the token payload if valid and unexpired, else None."""
    try:
        body, sig = token.rsplit(".", 1)
        expected = _hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(expected, sig):
            return None
        payload = _json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if int(payload["exp"]) < int(time.time()):
            return None
        if not payload.get("artifact_id") or not payload.get("owner_id"):
            return None
        return payload
    except Exception:
        return None
