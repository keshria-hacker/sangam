"""extensions_routes.py — unified extension catalogue API.

Lists every registered extension (tools, skills, providers, capabilities, MCP
servers) and toggles them on/off. Registers onto the shared ``router`` from
``.common`` like every other route module; the facade (``backend/api.py``)
imports this module so the endpoints mount under ``/api``.
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ..extensions import ExtensionKind, initialize_extensions, is_initialized
from ..extensions.registry import extensions
from .common import router


class ExtensionOut(BaseModel):
    """Public view of one extension."""

    name: str = Field(
        description="Registry name, e.g. 'tool:web_search' or 'skill:debugging'"
    )
    version: str = Field(description="Semantic version MAJOR.MINOR.PATCH")
    kind: str = Field(description="Extension kind: tool | skill | provider | capability | mcp_server")
    description: str = ""
    enabled: bool = True


class ExtensionListOut(BaseModel):
    extensions: list[ExtensionOut]


class ExtensionToggleOut(BaseModel):
    name: str
    enabled: bool


def _ensure_initialized() -> None:
    """Lazily seed the registry on first request (import-safe for tests)."""
    if not is_initialized() and not extensions.list_all():
        initialize_extensions()


def _to_out(name: str) -> ExtensionOut:
    manifest = extensions.get(name)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"Extension not found: {name}")
    return ExtensionOut(
        name=manifest.name,
        version=manifest.version,
        kind=manifest.kind.value
        if isinstance(manifest.kind, ExtensionKind)
        else str(manifest.kind),
        description=manifest.description,
        enabled=extensions.is_enabled(name),
    )


@router.get("/extensions", response_model=ExtensionListOut)
def list_extensions() -> ExtensionListOut:
    """List every registered extension with its current enabled state."""
    _ensure_initialized()
    return ExtensionListOut(extensions=[_to_out(m.name) for m in extensions.list_all()])


@router.post("/extensions/{name}/enable", response_model=ExtensionToggleOut)
def enable_extension(name: str) -> ExtensionToggleOut:
    """Enable an extension by registry name."""
    _ensure_initialized()
    if not extensions.enable(name):
        raise HTTPException(status_code=404, detail=f"Extension not found: {name}")
    return ExtensionToggleOut(name=name, enabled=True)


@router.post("/extensions/{name}/disable", response_model=ExtensionToggleOut)
def disable_extension(name: str) -> ExtensionToggleOut:
    """Disable an extension by registry name."""
    _ensure_initialized()
    if not extensions.disable(name):
        raise HTTPException(status_code=404, detail=f"Extension not found: {name}")
    return ExtensionToggleOut(name=name, enabled=False)
