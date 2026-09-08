"""
schemas.py — Pydantic models for request validation and API responses.
Kept separate from models.py (SQLAlchemy) so persistence and the wire
format can evolve independently.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.response_events import ModelCapabilities



class ChatMessageIn(BaseModel):
    role: str = Field(pattern="^(user|assistant|system)$")
    content: str = Field(min_length=1, max_length=100_000, description="Message content (max 100k chars)")

    @model_validator(mode="after")
    def content_not_empty(self) -> "ChatMessageIn":
        if not self.content.strip():
            raise ValueError("Message content cannot be empty or whitespace-only")
        return self


class ChatStreamRequest(BaseModel):
    chat_id: str | None = None                 # None => create a new chat
    model: str = Field(min_length=1, description="Model ID (required)")
    messages: list[ChatMessageIn] = Field(min_length=1, max_length=200, description="1-200 messages per request")
    file_ids: list[str] = Field(default_factory=list, max_length=10, description="Max 10 files per request")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, gt=0, le=128_000, description="Max tokens to generate (1-128k)")
    regenerate: bool = False                   # True => resend without re-persisting the user turn
    web_search: bool = False                   # True => augment the prompt with live web results
    reasoning_effort: str | None = Field(default=None, description="Reasoning effort: low, medium, high, etc.")

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
    created_at: datetime


class ChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    model: str
    created_at: datetime
    updated_at: datetime


class ChatDetailOut(ChatOut):
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
