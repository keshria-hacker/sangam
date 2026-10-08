"""Extension manifest: typed identity card for every pluggable unit in Sangam.

An *extension* is anything the platform can list, enable, and disable through one
surface: tools, skills, providers, capabilities, and MCP servers. Each carries
an :class:`ExtensionManifest` so the registry, the API, and the UI all speak
the same language.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = ["ExtensionKind", "ExtensionManifest", "SEMVER_RE"]


class ExtensionKind(StrEnum):
    """The kind of capability an extension provides."""

    TOOL = "tool"
    SKILL = "skill"
    PROVIDER = "provider"
    CAPABILITY = "capability"
    MCP_SERVER = "mcp_server"


# Strict MAJOR.MINOR.PATCH — pre-release/build metadata are rejected so that
# manifests stay comparable and sortable by plain tuple comparison.
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _validate_semver(version: str) -> str:
    if not isinstance(version, str) or not SEMVER_RE.match(version):
        raise ValueError(
            f"Invalid semantic version {version!r}: expected MAJOR.MINOR.PATCH "
            "(e.g. '1.2.0')"
        )
    return version


@dataclass
class ExtensionManifest:
    """Identity card for a single extension.

    Attributes:
        name: Unique registry name. Tool/skill adapters namespace these as
            ``tool:<name>`` and ``skill:<id>`` so the two worlds can never collide.
        version: Strict ``MAJOR.MINOR.PATCH`` string.
        kind: What the extension provides (tool, skill, provider, ...).
        description: Human-readable summary shown in the UI.
        entrypoint: Dotted path or locator for the backing implementation
            (e.g. ``backend.tools.builtin:web_search`` or a SKILL.md path).
        enabled_by_default: Whether the extension is active before any user
            override is persisted.
        config_schema: Optional JSON-schema-ish dict describing the
            extension's own configuration surface.
    """

    name: str
    version: str
    kind: ExtensionKind
    description: str = ""
    entrypoint: str = ""
    enabled_by_default: bool = True
    config_schema: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.version = _validate_semver(self.version)
        if isinstance(self.kind, str):
            # Tolerate plain strings so manifests built from JSON/YAML work.
            self.kind = ExtensionKind(self.kind)

    def version_tuple(self) -> tuple[int, int, int]:
        """Return ``(major, minor, patch)`` for ordering comparisons."""
        return tuple(int(part) for part in self.version.split("."))  # type: ignore[return-value]
