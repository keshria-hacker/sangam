"""
models.py — SQLAlchemy ORM tables. Pydantic request/response shapes live
in schemas.py; keep persistence and validation concerns separate.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, Text, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .security import EncryptionError, decrypt_field, encrypt_field


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255), default="New chat")
    model: Mapped[str] = mapped_column(String(64), default="")
    # Phase 5: rolling conversation summary + topics for cross-session memory.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_topics: Mapped[str | None] = mapped_column(String(500), nullable=True)  # comma-separated
    summarized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(UTC), onupdate=datetime.now(UTC))

    messages: Mapped[list["Message"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))          # "user" | "assistant" | "system"
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_ids: Mapped[str | None] = mapped_column(String(255), nullable=True)  # comma-separated
    response_time: Mapped[float | None] = mapped_column(nullable=True)  # seconds
    # User quality feedback on assistant messages: "up" | "down" | None.
    # feedback_note holds an optional free-text reason accompanying "down".
    feedback: Mapped[str | None] = mapped_column(String(8), nullable=True)
    feedback_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON list of MediaAttachment dicts (image/audio), foundation for
    # voice + image-generation integrations. NULL => text-only message.
    media_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(UTC))

    chat: Mapped["Chat"] = relationship(back_populates="messages")


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    extension: Mapped[str] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(default=0)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(UTC))


class ProviderKey(Base):
    """API keys added from the Settings UI at runtime. Encrypted at rest."""
    __tablename__ = "provider_keys"

    provider_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    api_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(UTC), onupdate=datetime.now(UTC)
    )

    # --- Hybrids for transparent encrypt/decrypt ---
    @hybrid_property
    def api_key(self) -> str:
        try:
            return decrypt_field(self.api_key_encrypted) if self.api_key_encrypted else ""
        except EncryptionError:
            return ""

    @api_key.setter
    def api_key(self, value: str) -> None:
        self.api_key_encrypted = encrypt_field(value)

    @api_key.expression
    def api_key(cls):
        # Not queryable (encrypted); use provider_id only for lookups
        return func.null()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_salt: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(UTC))

    preferences: Mapped["UserPreference | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    custom_agents: Mapped[list["CustomAgent"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserPreference(Base):
    """Per-user response style preferences (Implementation Plan Phase 4).

    Stored values OVERRIDE the Response Intelligence layer's detected
    user_prefers_concise/user_prefers_detailed signals in chat_stream.
    """

    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    response_style: Mapped[str] = mapped_column(String(16), default="balanced")  # concise|balanced|detailed
    formality: Mapped[str] = mapped_column(String(16), default="neutral")        # casual|neutral|formal
    expertise_level: Mapped[str] = mapped_column(String(16), default="general")  # beginner|general|expert
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(UTC), onupdate=datetime.now(UTC)
    )
    # Generic JSON blob for the typed settings schema (Phase 2)
    settings_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="preferences")


class AgentRun(Base):
    """Agent run history (Phase 3)."""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # agent | code-agent | team
    title: Mapped[str] = mapped_column(String(200))
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="done")
    tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    steps_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class Artifact(Base):
    """Typed artifact (Phase 4)."""

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(16), default="doc")  # doc | diagram | code | html
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    versions: Mapped[list["ArtifactVersion"]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan")


class ArtifactVersion(Base):
    """Artifact version history."""

    __tablename__ = "artifact_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column()
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    artifact: Mapped["Artifact"] = relationship(back_populates="versions")

class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(UTC))


class PasswordResetToken(Base):
    """One-time password reset token with a 30-minute expiry.

    Tokens are single-use: ``used`` is flipped to ``True`` on successful
    reset so a leaked token cannot be replayed.
    """
    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
    used: Mapped[bool] = mapped_column(default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(UTC))


class AnalyticsEvent(Base):
    """Local-first usage event (openpanel-style, opt-in via FEATURE_ANALYTICS).

    Only aggregate-friendly data is stored: event type + small JSON
    properties. No message content, no prompts — ever.
    """

    __tablename__ = "analytics_events"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    properties: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(UTC), index=True)


class CustomAgent(Base):
    """User-defined agent configuration (Agent Hub, Phase 3)."""

    __tablename__ = "custom_agents"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_names: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    max_steps: Mapped[int] = mapped_column(default=8)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(UTC), onupdate=datetime.now(UTC)
    )

    user: Mapped["User"] = relationship(back_populates="custom_agents")

class Automation(Base):
    """Scheduled automation (Phase 5)."""

    __tablename__ = "automations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    trigger: Mapped[str] = mapped_column(String(64))  # hourly|daily|weekly|cron
    action: Mapped[str] = mapped_column(String(32))  # agent|chat
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(default=True)
    last_run: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
