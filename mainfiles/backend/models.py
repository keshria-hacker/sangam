"""
models.py — SQLAlchemy ORM tables. Pydantic request/response shapes live
in schemas.py; keep persistence and validation concerns separate.
"""
import uuid
from datetime import UTC, datetime

from backend.database import Base
from backend.security import EncryptionError, decrypt_field, encrypt_field
from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, Text, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255), default="New chat")
    model: Mapped[str] = mapped_column(String(64), default="")
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
