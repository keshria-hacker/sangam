"""
hive.py — Persistent Teams v2: the on-disk hive (munder-difflin core,
minus the office floor / PTY layer, which Sangam does not have).

Layout under one hive root (default ``mainfiles/hive/``, overridable
per Hive instance so tests use a tmp dir)::

    registry.json            id -> {role, cwd, session, archived, send_only}
    agents/<id>/identity.md  who the agent is
    agents/<id>/memory.md    durable notes
    agents/<id>/inbox/       one JSON file per delivered message
    agents/<id>/outbox/      one JSON file per message the agent wrote
    agents/<id>/cursor.json  last-drained outbox position
    board.md                 shared board (human-readable)
    log.jsonl                append-only routing log

Routing rules (``route_messages``), copied from the reference
behaviour, not its branding:

- ``to == "human"`` resolves to ``god`` — god is the human's proxy.
  There is NO separate human-approval queue here; approvals reuse
  Sangam's existing approval path.
- Broadcast fans out via ``select_broadcast_targets``: live agents
  only — archived and send-only agents are skipped.
- Archived recipient: the mail is still filed in its inbox AND the
  sender is told at once (a reply in the sender's inbox) when a reply
  was expected — never a silent dead end.
- Undeliverable mail (unknown recipient) bounces to god with a
  ``[bounced]`` subject — never silently dropped.
- A delivered message to a live agent is recorded in ``log.jsonl``.

Breaker (``Breaker``): server-side ladder
``healthy -> steering -> constrained -> stopped``, one level per
beat, de-escalating one level per healthy beat. ``hard_stop`` is OFF
by default, so without it the ladder caps at ``constrained`` and
never kills an agent. Beats are driven by the caller (a server tick),
never by a browser timer.

Closing time (``closing_time_broadcast`` / ``collect_acks``): a
graceful shutdown protocol, not a kill. Broadcast ``CLOSING TIME`` to
all live agents, collect per-agent ``CLOSING-TIME-ACK`` messages
(subject matched exactly, sender must be a live worker), and only
god's ``COMPLETE`` honours shutdown. A grace period / hard-quit
fallback is the caller's decision, recorded in the log.

This module is pure filesystem + stdlib: no LLM, no DB, no routes.
Routes (wired by the parent) call into it; tests drive it directly.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GOD_ID = "god"
HUMAN_ALIAS = "human"
CLOSING_TIME_SUBJECT = "CLOSING TIME"
CLOSING_TIME_ACK_SUBJECT = "CLOSING-TIME-ACK"
CLOSING_TIME_COMPLETE_SUBJECT = "COMPLETE"

BREAKER_LEVELS = ["healthy", "steering", "constrained", "stopped"]


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@dataclass
class HiveMessage:
    id: str
    sender: str
    recipient: str
    subject: str
    body: str
    reply_expected: bool = False
    broadcast: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "sender": self.sender, "recipient": self.recipient,
            "subject": self.subject, "body": self.body,
            "reply_expected": self.reply_expected, "broadcast": self.broadcast,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HiveMessage":
        return cls(
            id=str(data.get("id") or _new_id("msg")),
            sender=str(data.get("sender", "")),
            recipient=str(data.get("recipient", "")),
            subject=str(data.get("subject", "")),
            body=str(data.get("body", "")),
            reply_expected=bool(data.get("reply_expected", False)),
            broadcast=bool(data.get("broadcast", False)),
        )


@dataclass
class AgentRecord:
    id: str
    role: str = ""
    cwd: str = ""
    session: str = ""
    archived: bool = False
    send_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "role": self.role, "cwd": self.cwd,
                "session": self.session, "archived": self.archived,
                "send_only": self.send_only}


class Hive:
    """One on-disk hive. All writes are atomic (tmp + rename)."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.agents_dir = self.root / "agents"
        self.root.mkdir(parents=True, exist_ok=True)
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        if not (self.root / "board.md").exists():
            (self.root / "board.md").write_text("# Hive board\n", encoding="utf-8")

    # ------------------------------------------------------------ registry

    def _registry_path(self) -> Path:
        return self.root / "registry.json"

    def load_registry(self) -> dict[str, AgentRecord]:
        path = self._registry_path()
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        out: dict[str, AgentRecord] = {}
        for agent_id, data in (raw or {}).items():
            if isinstance(data, dict):
                out[agent_id] = AgentRecord(id=agent_id, role=data.get("role", ""),
                                            cwd=data.get("cwd", ""), session=data.get("session", ""),
                                            archived=bool(data.get("archived", False)),
                                            send_only=bool(data.get("send_only", False)))
        return out

    def _save_registry(self, registry: dict[str, AgentRecord]) -> None:
        _atomic_write(self._registry_path(),
                      json.dumps({k: v.to_dict() for k, v in registry.items()}, indent=2))

    def create_agent(self, agent_id: str, role: str, cwd: str = "",
                     session: str = "", identity: str = "") -> AgentRecord:
        agent_id = (agent_id or "").strip()
        if not agent_id or "/" in agent_id or "\\" in agent_id or agent_id in (".", ".."):
            raise ValueError("agent_id must be a plain, non-empty name")
        registry = self.load_registry()
        if agent_id in registry:
            raise ValueError(f"agent already exists: {agent_id}")
        record = AgentRecord(id=agent_id, role=role, cwd=cwd, session=session or agent_id)
        adir = self.agents_dir / agent_id
        (adir / "inbox").mkdir(parents=True, exist_ok=True)
        (adir / "outbox").mkdir(parents=True, exist_ok=True)
        (adir / "identity.md").write_text(identity or f"# {agent_id}\nRole: {role}\n",
                                          encoding="utf-8")
        (adir / "memory.md").write_text("", encoding="utf-8")
        (adir / "cursor.json").write_text(json.dumps({"last_drained": None}), encoding="utf-8")
        registry[agent_id] = record
        self._save_registry(registry)
        self._log("agent.created", {"agent_id": agent_id, "role": role})
        return record

    def archive_agent(self, agent_id: str) -> AgentRecord:
        registry = self.load_registry()
        record = registry.get(agent_id)
        if record is None:
            raise ValueError(f"unknown agent: {agent_id}")
        record.archived = True
        self._save_registry(registry)
        self._log("agent.archived", {"agent_id": agent_id})
        return record

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        return self.load_registry().get(agent_id)

    # ------------------------------------------------------------- mailboxes

    def _agent_dir(self, agent_id: str) -> Path:
        return self.agents_dir / agent_id

    def send_message(self, sender: str, recipient: str, subject: str, body: str,
                     reply_expected: bool = False, broadcast: bool = False) -> HiveMessage:
        """Write a message into the SENDER's outbox (drained by routing).

        God may also be the sender; messages from unknown senders are
        still recorded (the router bounces them) rather than refused
        silently — refusal would lose the sender's intent.
        """
        msg = HiveMessage(id=_new_id("msg"), sender=sender, recipient=recipient,
                          subject=subject, body=body, reply_expected=reply_expected,
                          broadcast=broadcast)
        outbox = self._agent_dir(sender) / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        _atomic_write(outbox / f"{msg.id}.json", json.dumps(msg.to_dict(), indent=2))
        return msg

    def _deliver(self, recipient: str, msg: HiveMessage) -> None:
        inbox = self._agent_dir(recipient) / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        _atomic_write(inbox / f"{msg.id}.json", json.dumps(msg.to_dict(), indent=2))

    def _notify(self, recipient: str, subject: str, body: str, sender: str = GOD_ID) -> None:
        note = HiveMessage(id=_new_id("msg"), sender=sender, recipient=recipient,
                           subject=subject, body=body)
        self._deliver(recipient, note)

    def inbox_messages(self, agent_id: str) -> list[HiveMessage]:
        inbox = self._agent_dir(agent_id) / "inbox"
        out: list[HiveMessage] = []
        if not inbox.exists():
            return out
        for path in sorted(inbox.glob("*.json")):
            try:
                out.append(HiveMessage.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, OSError):
                continue
        return out

    def outbox_messages(self, agent_id: str) -> list[HiveMessage]:
        outbox = self._agent_dir(agent_id) / "outbox"
        out: list[HiveMessage] = []
        if not outbox.exists():
            return out
        for path in sorted(outbox.glob("*.json")):
            try:
                out.append(HiveMessage.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, OSError):
                continue
        return out

    def select_broadcast_targets(self, registry: dict[str, AgentRecord],
                                 sender: str) -> list[str]:
        """Live agents only: archived and send-only agents never receive
        broadcasts, and the sender never receives its own broadcast."""
        return [aid for aid, rec in registry.items()
                if aid != sender and not rec.archived and not rec.send_only]

    def route_messages(self) -> dict[str, Any]:
        """Drain every agent's outbox into recipients' inboxes.

        Returns a summary: delivered / bounced / archived_notified /
        filed counts. Bounce-never-drop: undeliverable mail goes to god
        with a ``[bounced]`` subject; archived recipients get their mail
        filed plus an immediate notice to the sender when a reply was
        expected.
        """
        registry = self.load_registry()
        summary = {"delivered": 0, "bounced": 0, "archived_notified": 0, "filed_archived": 0}
        for agent_id in sorted(registry):
            outbox = self._agent_dir(agent_id) / "outbox"
            if not outbox.exists():
                continue
            for path in sorted(outbox.glob("*.json")):
                try:
                    msg = HiveMessage.from_dict(json.loads(path.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, OSError):
                    continue
                # Resolve the human alias to god BEFORE any other rule.
                recipient = GOD_ID if msg.recipient == HUMAN_ALIAS else msg.recipient
                if msg.broadcast:
                    for target in self.select_broadcast_targets(registry, msg.sender):
                        self._deliver(target, msg)
                        summary["delivered"] += 1
                    self._log("message.broadcast", {"id": msg.id, "sender": msg.sender})
                elif recipient not in registry:
                    self._notify(GOD_ID, f"[bounced] {msg.subject}",
                                 f"Undeliverable message {msg.id} from {msg.sender} "
                                 f"to {msg.recipient}: no such agent.")
                    summary["bounced"] += 1
                    self._log("message.bounced", {"id": msg.id, "sender": msg.sender,
                                                  "recipient": msg.recipient})
                elif registry[recipient].archived:
                    # File it AND tell the sender at once if a reply was expected.
                    self._deliver(recipient, msg)
                    summary["filed_archived"] += 1
                    if msg.reply_expected and msg.sender in registry:
                        self._notify(msg.sender, "Recipient archived",
                                     f"No one is there to answer: {recipient} is archived; "
                                     f"your message {msg.id} was filed but will not be answered.")
                        summary["archived_notified"] += 1
                    self._log("message.archived_recipient", {"id": msg.id, "recipient": recipient})
                else:
                    self._deliver(recipient, msg)
                    summary["delivered"] += 1
                    self._log("message.delivered", {"id": msg.id, "sender": msg.sender,
                                                    "recipient": recipient})
                path.unlink(missing_ok=True)
                self._mark_cursor(agent_id, msg.id)
        return summary

    def _mark_cursor(self, agent_id: str, msg_id: str) -> None:
        cursor = self._agent_dir(agent_id) / "cursor.json"
        _atomic_write(cursor, json.dumps({"last_drained": msg_id}))

    # --------------------------------------------------------- closing time

    def closing_time_broadcast(self) -> HiveMessage:
        """Broadcast CLOSING TIME from god to all live agents."""
        registry = self.load_registry()
        msg = HiveMessage(id=_new_id("msg"), sender=GOD_ID, recipient="*",
                          subject=CLOSING_TIME_SUBJECT,
                          body="Closing time: finish up and reply with a CLOSING-TIME-ACK.",
                          broadcast=True)
        for target in self.select_broadcast_targets(registry, GOD_ID):
            self._deliver(target, msg)
        self._log("closing_time.broadcast", {"id": msg.id})
        return msg

    def collect_acks(self) -> dict[str, Any]:
        """Collect CLOSING-TIME-ACKs from god's inbox.

        An ACK counts only when its subject matches exactly and its
        sender is a live (non-archived) worker. Returns the acking
        agent ids and whether god's COMPLETE is present (the only
        COMPLETE that honours shutdown).
        """
        registry = self.load_registry()
        acks: list[str] = []
        god_complete = False
        for msg in self.inbox_messages(GOD_ID):
            if msg.subject == CLOSING_TIME_ACK_SUBJECT:
                rec = registry.get(msg.sender)
                if rec is not None and not rec.archived:
                    acks.append(msg.sender)
            if msg.subject == CLOSING_TIME_COMPLETE_SUBJECT and msg.sender == GOD_ID:
                god_complete = True
        live = [aid for aid, rec in registry.items() if aid != GOD_ID and not rec.archived]
        return {"acked": sorted(set(acks)), "missing": sorted(set(live) - set(acks)),
                "god_complete": god_complete, "all_acked": set(live) <= set(acks)}

    # ------------------------------------------------------------------ log

    def _log(self, event: str, data: dict[str, Any]) -> None:
        line = json.dumps({"ts": time.time(), "event": event, **data})
        path = self.root / "log.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


@dataclass
class Breaker:
    """Server-side circuit breaker ladder (policy only; the caller's
    beat enforces). One level per beat, never jumping to kill;
    de-escalates one level per healthy beat. ``hard_stop`` OFF by
    default caps the ladder at ``constrained`` — it never kills."""
    hard_stop: bool = False
    level: str = "healthy"
    _consecutive_healthy: int = field(default=0, repr=False)

    def beat(self, *, unhealthy: bool, reason: str = "") -> str:
        """Advance one beat. ``unhealthy`` = cost/velocity spike, an
        error storm, or no-progress signal this beat. Returns the new
        level. The reason is recorded by the caller, not here."""
        idx = BREAKER_LEVELS.index(self.level)
        if unhealthy:
            self._consecutive_healthy = 0
            cap = len(BREAKER_LEVELS) - 1 if self.hard_stop else len(BREAKER_LEVELS) - 2
            self.level = BREAKER_LEVELS[min(idx + 1, cap)]
        else:
            self._consecutive_healthy += 1
            self.level = BREAKER_LEVELS[max(idx - 1, 0)]
        return self.level

    @property
    def stopped(self) -> bool:
        return self.level == "stopped"

    @property
    def action(self) -> str:
        """What the caller should do at this level."""
        return {"healthy": "none", "steering": "steer",
                "constrained": "constrain", "stopped": "stop"}[self.level]
