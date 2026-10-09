"""
schemas.py — Pydantic models for request validation and API responses.
Kept separate from models.py (SQLAlchemy) so persistence and the wire
format can evolve independently.
"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

import json

from .response_events import ModelCapabilities


class MessageContentPart(BaseModel):
    """One multimodal content part: text, image, or audio.

    Binary payloads are referenced by URL (served from /api/media/...) rather
    than inlined, keeping request bodies small. `data` may carry a data-URI
    for small inline payloads.
    """

    type: Literal["text", "image", "audio"]
    text: str | None = None
    url: str | None = None
    data: str | None = None            # data-URI for small inline payloads
    mime_type: str | None = None       # e.g. "image/png", "audio/webm"


class MediaAttachment(BaseModel):
    """A persisted media file attached to a message (image or audio)."""

    id: str
    kind: Literal["image", "audio"]
    filename: str
    mime_type: str
    size_bytes: int
    url: str                           # GET /api/media/{id}
    created_at: datetime | None = None


class ChatMessageIn(BaseModel):
    role: str = Field(pattern="^(user|assistant|system)$")
    content: str = Field(min_length=1, max_length=100_000, description="Message content (max 100k chars)")
    # Optional multimodal parts (foundation for voice/image). When present,
    # providers that support vision/audio receive them as content parts.
    parts: list[MessageContentPart] | None = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def content_not_empty(self) -> "ChatMessageIn":
        if not self.content.strip() and not self.parts:
            raise ValueError("Message content cannot be empty or whitespace-only")
        return self


class ChatStreamRequest(BaseModel):
    chat_id: str | None = None                 # None => create a new chat
    model: str = Field(min_length=1, description="Model ID (required)")
    messages: list[ChatMessageIn] = Field(min_length=1, max_length=200, description="1-200 messages per request")
    file_ids: list[str] = Field(default_factory=list, max_length=10, description="Max 10 files per request")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0, le=128_000, description="Max tokens to generate (1-128k); null = provider default")
    regenerate: bool = False                   # True => resend without re-persisting the user turn
    web_search: bool = False                   # True => augment the prompt with live web results
    reasoning_effort: str | None = Field(default=None, description="Reasoning effort: low, medium, high, etc.")
    media_ids: list[str] = Field(default_factory=list, max_length=10, description="Media attachment IDs (image/audio)")

    @model_validator(mode="after")
    def final_message_must_be_user(self) -> "ChatStreamRequest":
        if not self.messages or self.messages[-1].role != "user":
            raise ValueError("The final chat message must be from the user")
        return self


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    model: str | None = None
    response_time: float | None = None
    feedback: str | None = None
    feedback_note: str | None = None
    created_at: datetime
    # Multimodal attachments (image/audio). Serialized from Message.media_json.
    media: list[MediaAttachment] = Field(default_factory=list)
    content_type: str = "text"           # "text" | "multimodal"

    @model_validator(mode="before")
    @classmethod
    def _populate_media(cls, data: Any) -> Any:
        """Hydrate `media`/`content_type` from the ORM Message.media_json column."""
        if isinstance(data, dict):
            return data
        attachments: list[dict] = []
        media_json = getattr(data, "media_json", None)
        if media_json:
            try:
                parsed = json.loads(media_json)
                if isinstance(parsed, list):
                    attachments = parsed
            except (ValueError, TypeError):
                attachments = []
        return {
            "id": getattr(data, "id", None),
            "role": getattr(data, "role", None),
            "content": getattr(data, "content", None),
            "model": getattr(data, "model", None),
            "response_time": getattr(data, "response_time", None),
            "feedback": getattr(data, "feedback", None),
            "feedback_note": getattr(data, "feedback_note", None),
            "created_at": getattr(data, "created_at", None),
            "media": attachments,
            "content_type": "multimodal" if attachments else "text",
        }


class ChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    model: str
    summary: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatDetailOut(ChatOut):
    message_count: int = 0
    messages: list[MessageOut] = Field(default_factory=list)


class FileUploadOut(BaseModel):
    file_id: str
    filename: str
    extension: str
    size_bytes: int
    preview: str | None = None   # first ~300 chars of extracted text


class ProviderStatus(BaseModel):
    id: str
    label: str
    state: str          # "online" | "offline" | "local"


class ProviderKeyIn(BaseModel):
    api_key: str = Field(min_length=1, max_length=500)


class ProviderKeyOut(BaseModel):
    provider_id: str
    label: str = ""
    linked: bool
    masked_key: str | None = None   # e.g. "sk-ant-...9f2a"


class ModelInfo(BaseModel):
    id: str
    name: str
    provider: str
    litellm_id: str
    context_window: int | None = None
    # Providers supply a typed ModelCapabilities model (see response_events).
    # Declaring it here keeps the wire shape identical to the previous dict
    # while letting Pydantic validate provider objects instead of rejecting
    # them as "Input should be a valid dictionary".
    capabilities: ModelCapabilities | None = None


class ProviderModelEntry(BaseModel):
    """A single model entry returned by a provider's model listing API."""
    id: str
    name: str
    provider: str
    description: str = ""
    provider_label: str = ""


class RefreshModelsOut(BaseModel):
    """Response from the refresh-provider-models endpoint."""
    provider_id: str
    success: bool = True
    count: int = 0
    models: list[ProviderModelEntry] = Field(default_factory=list)


class AuthCredentialsIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=256)


class AuthStatusOut(BaseModel):
    registration_open: bool


class AuthTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    csrf_token: str | None = None  # Double-submit cookie CSRF token (set on login/register)


class ForgotPasswordIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class ForgotPasswordOut(BaseModel):
    message: str
    reset_token: str | None = None  # Shown directly in single-user mode (no email)


class ResetPasswordIn(BaseModel):
    reset_token: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class FeedbackIn(BaseModel):
    """User quality feedback on an assistant message.

    Sending the same value again clears the feedback (toggle-off undo).
    """

    value: Literal["up", "down"]
    note: str | None = Field(default=None, max_length=2000)


class UserPreferenceIn(BaseModel):
    """Per-user response style preferences (Phase 4)."""

    response_style: Literal["concise", "balanced", "detailed"] = "balanced"
    formality: Literal["casual", "neutral", "formal"] = "neutral"
    expertise_level: Literal["beginner", "general", "expert"] = "general"


class UserPreferenceOut(UserPreferenceIn):
    """Wire shape for GET /user/preferences (adds server metadata)."""

    user_id: str
    updated_at: datetime
