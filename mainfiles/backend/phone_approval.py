"""
phone_approval.py — Scoped phone-approval token (narrower alternative
to full LAN UI access).

Sangam's LAN pairing hands a phone the whole UI. Sometimes the phone
should answer exactly ONE queued approval and nothing else. This
module issues that token:

- A token is good for exactly ONE queued approval decision, matched
  to the EXACT request it was issued for: the approval id plus a
  fingerprint of the request (tool + capped command preview + session
  id). Presenting the token against a different request fails, even
  before the single-use check — a token can never be replayed onto a
  newer, scarier request.
- The server stores ONLY the SHA-256 hash of the token (same pattern
  as LAN device tokens): the raw token is returned exactly once, at
  issue time, and never again. A stolen store yields no usable token.
- Tokens expire (default 15 minutes) and are single-use: a successful
  consume marks the token used, and any second use fails.
- A token is NEVER full-account access: it carries no user session,
  no LAN device token, and no authority beyond the one decision named
  in it. It cannot list, read, or act on anything else; routes must
  check the token against the queued approval and then apply the
  decision through the normal approval path (including the queue's
  stale-click head check).

Persistence: when a ``store_path`` is given, issued tokens are
written atomically (hashes only) and reloaded on init. The
SQLAlchemy row follows the lan_pairing pattern for routes that want
DB durability instead of the JSON store.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

TOKEN_TTL_S = 900  # 15 minutes


def _now() -> datetime:
    return datetime.now(UTC)


class PhoneApprovalTokenRow(Base):
    """Durable row for one scoped phone-approval token (hash only)."""

    __tablename__ = "phone_approval_tokens"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(64), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    used: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


def request_fingerprint(approval_id: str, tool: str, command_preview: str,
                        session_id: str = "") -> str:
    """Fingerprint binding a token to the exact request: approval id
    + tool + capped command preview + session. Any change to the
    request changes the fingerprint, so the token stops matching."""
    material = "\n".join([approval_id or "", tool or "",
                          (command_preview or "")[:2000], session_id or ""])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class PhoneApprovalToken:
    id: str
    approval_id: str
    token_hash: str
    fingerprint: str
    used: bool = False
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + TOKEN_TTL_S)

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "approval_id": self.approval_id,
                "token_hash": self.token_hash, "fingerprint": self.fingerprint,
                "used": self.used, "created_at": self.created_at,
                "expires_at": self.expires_at}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PhoneApprovalToken":
        return cls(id=str(data["id"]), approval_id=data["approval_id"],
                   token_hash=data["token_hash"], fingerprint=data["fingerprint"],
                   used=bool(data.get("used", False)),
                   created_at=float(data.get("created_at", time.time())),
                   expires_at=float(data.get("expires_at", time.time() + TOKEN_TTL_S)))


class PhoneApprovalStore:
    """Issue + consume scoped tokens. Raw tokens exist only in the
    return value of ``issue``; the store holds hashes."""

    def __init__(self, store_path: str | Path | None = None):
        self.store_path = Path(store_path) if store_path else None
        self._tokens: list[PhoneApprovalToken] = []
        if self.store_path and self.store_path.exists():
            try:
                raw = json.loads(self.store_path.read_text(encoding="utf-8"))
                self._tokens = [PhoneApprovalToken.from_dict(item) for item in raw]
            except (json.JSONDecodeError, OSError, KeyError, TypeError):
                self._tokens = []

    def _persist(self) -> None:
        if not self.store_path:
            return
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store_path.with_suffix(self.store_path.suffix + ".tmp")
        tmp.write_text(json.dumps([t.to_dict() for t in self._tokens], indent=2),
                       encoding="utf-8")
        tmp.replace(self.store_path)

    def issue(self, approval_id: str, tool: str, command_preview: str,
              session_id: str = "") -> dict[str, Any]:
        """Issue a token for one approval. Returns the raw token
        exactly once (plus its id/expiry for the caller to display);
        the store keeps only the hash."""
        raw = secrets.token_urlsafe(32)
        token = PhoneApprovalToken(
            id=f"pa-{uuid.uuid4().hex[:12]}", approval_id=approval_id,
            token_hash=_hash_token(raw),
            fingerprint=request_fingerprint(approval_id, tool, command_preview, session_id))
        self._tokens.append(token)
        self._persist()
        return {"token": raw, "token_id": token.id, "approval_id": approval_id,
                "expires_at": token.expires_at,
                "scope": "one approval decision only — not account access"}

    def consume(self, raw_token: str, approval_id: str, tool: str,
                command_preview: str, decision: str,
                session_id: str = "") -> dict[str, Any]:
        """Consume a token for one decision. Fails (without consuming)
        on: unknown token, expired token, already-used token, approval
        mismatch, or request-fingerprint mismatch. Succeeds exactly
        once, returning the decision for the caller to apply through
        the normal approval path."""
        if decision not in ("allow", "deny"):
            return {"ok": False, "error": "decision must be 'allow' or 'deny'"}
        token_hash = _hash_token(raw_token or "")
        token = next((t for t in self._tokens if t.token_hash == token_hash), None)
        if token is None:
            return {"ok": False, "error": "unknown token"}
        if token.used:
            return {"ok": False, "error": "token already used"}
        if token.expired:
            return {"ok": False, "error": "token expired"}
        if token.approval_id != approval_id:
            return {"ok": False, "error": "token is for a different approval"}
        if token.fingerprint != request_fingerprint(approval_id, tool, command_preview, session_id):
            return {"ok": False, "error": "request changed since the token was issued"}
        token.used = True
        self._persist()
        return {"ok": True, "approval_id": approval_id, "decision": decision,
                "token_id": token.id}
