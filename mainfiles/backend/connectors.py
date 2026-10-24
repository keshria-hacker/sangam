"""
connectors.py — Phase 5 (all-in-one plan): generic OAuth connector framework.

A connector is a definition, not a hard-coded integration: name,
authorize/token URLs, scopes, and the env vars holding its client
credentials. Built-ins cover GitHub and Google; anything else can be
registered at runtime (or via ``SANGAM_CUSTOM_CONNECTORS`` JSON in
the future — the registry API is the extension point).

Tokens are stored encrypted at rest by reusing the existing
ProviderKey row (provider_id ``oauth:<name>``) with a JSON value
{access_token, refresh_token, expires_at}. No token ever lands in a
log or a plain-text column.

State tokens are HMAC-signed with MASTER_KEY and carry a nonce kept
in memory for 10 minutes; a callback with an unknown or expired
state is rejected before any token exchange happens.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

@dataclass
class ConnectorDefinition:
    name: str
    label: str
    authorize_url: str
    token_url: str
    scopes: list[str] = field(default_factory=list)
    client_id_env: str = ""
    client_secret_env: str = ""

    @property
    def client_id(self) -> str:
        return os.environ.get(self.client_id_env, "")

    @property
    def client_secret(self) -> str:
        return os.environ.get(self.client_secret_env, "")

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


_REGISTRY: dict[str, ConnectorDefinition] = {}


def _builtins() -> list[ConnectorDefinition]:
    return [
        ConnectorDefinition(
            name="github", label="GitHub",
            authorize_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            scopes=["repo", "read:user"],
            client_id_env="OAUTH_GITHUB_CLIENT_ID",
            client_secret_env="OAUTH_GITHUB_CLIENT_SECRET",
        ),
        ConnectorDefinition(
            name="google", label="Google",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
            client_id_env="OAUTH_GOOGLE_CLIENT_ID",
            client_secret_env="OAUTH_GOOGLE_CLIENT_SECRET",
        ),
    ]


def get_registry() -> dict[str, ConnectorDefinition]:
    if not _REGISTRY:
        for definition in _builtins():
            _REGISTRY[definition.name] = definition
    return _REGISTRY


def register_connector(definition: ConnectorDefinition) -> None:
    get_registry()[definition.name] = definition


def _master_key_bytes() -> bytes:
    # HMAC key material only (not encryption): SHA-256 of the master
    # key string is deterministic across restarts, which state tokens
    # need, and never exposes the key itself.
    raw = os.environ.get("MASTER_KEY", "") or "sangam-dev-fallback"
    return hashlib.sha256(raw.encode()).digest()


def make_state(connector: str, user_id: str) -> str:
    """Create a state token: nonce + HMAC(nonce, connector, user)."""
    nonce = secrets.token_urlsafe(16)
    sig = hmac.new(_master_key_bytes(), f"{nonce}:{connector}:{user_id}".encode(),
                   hashlib.sha256).hexdigest()
    _STATE_NONCES[nonce] = (connector, user_id, time.time() + 600)
    return f"{nonce}.{sig}"


_STATE_NONCES: dict[str, tuple[str, str, float]] = {}


def verify_state(state: str) -> tuple[str, str] | None:
    """Return (connector, user_id) for a valid, unexpired state, else None."""
    try:
        nonce, sig = state.split(".", 1)
    except ValueError:
        return None
    entry = _STATE_NONCES.get(nonce)
    if not entry:
        return None
    connector, user_id, expiry = entry
    if time.time() > expiry:
        _STATE_NONCES.pop(nonce, None)
        return None
    expected = hmac.new(_master_key_bytes(), f"{nonce}:{connector}:{user_id}".encode(),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    _STATE_NONCES.pop(nonce, None)
    return connector, user_id


def authorize_url(definition: ConnectorDefinition, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": definition.client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(definition.scopes),
        "state": state,
        "response_type": "code",
    }
    return f"{definition.authorize_url}?{urlencode(params)}"
