"""Unified extension registry.

Sangam historically kept two separate worlds — the tool registry
(``backend.tools``) and the skill registry (``backend.skills``) — each with its
own enable/disable semantics. This module unifies them behind
:class:`ExtensionManifest`: every tool and skill is projected into one
registry with one enable/disable surface, while the original registries keep
working untouched.

Enable/disable state is persisted as a JSON delta file at
``{mainfiles}/extensions_state.json``: only names whose state differs from the
manifest's ``enabled_by_default`` are stored, so the file stays tiny and new
extensions pick up their defaults automatically.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .manifest import ExtensionKind, ExtensionManifest

logger = logging.getLogger(__name__)

# mainfiles/backend/extensions/registry.py -> parents[2] == mainfiles/
BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_STATE_PATH = BASE_DIR / "extensions_state.json"


class ExtensionRegistry:
    """Central registry for extension manifests with persisted enable/disable state."""

    def __init__(self, state_path: Path | None = None) -> None:
        self._manifests: dict[str, ExtensionManifest] = {}
        self._state_path = state_path or DEFAULT_STATE_PATH
        self._overrides: dict[str, bool] = {}
        self._load_state()

    # ------------------------------------------------------------------ state
    @property
    def state_path(self) -> Path:
        """Filesystem path of the persisted enable/disable delta file."""
        return self._state_path

    @state_path.setter
    def state_path(self, value: Path | str) -> None:
        self._state_path = Path(value)
        self._overrides = {}
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted overrides; never crash on corrupt state."""
        try:
            if not self._state_path.exists():
                return
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._overrides = {
                    str(name): bool(enabled) for name, enabled in data.items()
                }
            else:
                logger.warning(
                    "Ignoring malformed extensions state at %s: expected a JSON object",
                    self._state_path,
                )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "Could not load extensions state from %s (%s); continuing with defaults",
                self._state_path,
                exc,
            )

    def _save_state(self) -> None:
        """Persist only the overrides that differ from manifest defaults."""
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            deltas = {
                name: enabled
                for name, enabled in self._overrides.items()
                if name in self._manifests
                and self._manifests[name].enabled_by_default is not enabled
            }
            self._overrides = deltas
            self._state_path.write_text(
                json.dumps(deltas, indent=2, sort_keys=True), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning(
                "Could not persist extensions state to %s (%s)",
                self._state_path,
                exc,
            )

    # ------------------------------------------------------------- registry
    def register(self, manifest: ExtensionManifest) -> None:
        """Register a manifest; re-registering the same name overwrites."""
        if manifest.name in self._manifests:
            logger.warning(
                "Extension %r already registered, overwriting", manifest.name
            )
        self._manifests[manifest.name] = manifest
        self._save_state()
        logger.info("Registered extension: %s (%s)", manifest.name, manifest.kind.value)

    def get(self, name: str) -> ExtensionManifest | None:
        """Return the manifest for *name*, or ``None``."""
        return self._manifests.get(name)

    def list_all(self) -> list[ExtensionManifest]:
        """All registered manifests, in registration order."""
        return list(self._manifests.values())

    def list_enabled(self) -> list[ExtensionManifest]:
        """Only the manifests currently enabled."""
        return [m for m in self._manifests.values() if self.is_enabled(m.name)]

    def list_by_kind(self, kind: ExtensionKind) -> list[ExtensionManifest]:
        """All manifests of a given kind."""
        return [m for m in self._manifests.values() if m.kind == kind]

    # --------------------------------------------------------------- state
    def is_enabled(self, name: str) -> bool:
        manifest = self._manifests.get(name)
        if manifest is None:
            return False
        return self._overrides.get(name, manifest.enabled_by_default)

    def enable(self, name: str) -> bool:
        """Enable an extension; returns ``False`` if unknown."""
        if name not in self._manifests:
            return False
        self._overrides[name] = True
        self._save_state()
        return True

    def disable(self, name: str) -> bool:
        """Disable an extension; returns ``False`` if unknown."""
        if name not in self._manifests:
            return False
        self._overrides[name] = False
        self._save_state()
        return True

    def clear(self) -> None:
        """Remove all manifests and overrides (used by tests)."""
        self._manifests.clear()
        self._overrides.clear()

    def unregister(self, name: str) -> bool:
        """Remove one manifest and its override; returns ``False`` if unknown."""
        if name not in self._manifests:
            return False
        del self._manifests[name]
        self._overrides.pop(name, None)
        self._save_state()
        logger.info("Unregistered extension: %s", name)
        return True

    # -------------------------------------------------------------- adapters
    def register_tool_definition(self, tool_def: Any) -> ExtensionManifest:
        """Project a ``ToolDefinition`` into the extension registry.

        Manifest name: ``tool:<tool name>``. Re-registering overwrites.
        """
        manifest = ExtensionManifest(
            name=f"tool:{tool_def.name}",
            version="1.0.0",
            kind=ExtensionKind.TOOL,
            description=getattr(tool_def, "description", "") or "",
            entrypoint=f"backend.tools:{tool_def.name}",
        )
        self.register(manifest)
        return manifest

    def register_skill_definition(self, skill_def: Any) -> ExtensionManifest:
        """Project a ``SkillDefinition`` into the extension registry.

        Manifest name: ``skill:<skill id>``. Re-registering overwrites.
        """
        manifest = ExtensionManifest(
            name=f"skill:{skill_def.id}",
            version=getattr(skill_def, "version", "1.0.0") or "1.0.0",
            kind=ExtensionKind.SKILL,
            description=getattr(skill_def, "description", "") or "",
            entrypoint=f"backend.skills:{skill_def.id}",
        )
        self.register(manifest)
        return manifest


# Global registry instance
extensions = ExtensionRegistry()


def initialize_extensions() -> ExtensionRegistry:
    """(Re)sync every tool and skill into the unified extension registry.

    Imports are lazy (inside the function) so that importing
    ``backend.extensions`` never creates import cycles with the tool/skill
    packages. Safe to call multiple times: builtin tools are (re)registered,
    adapters overwrite on re-register, and stale ``tool:``/``skill:``
    manifests whose backing definition disappeared (e.g. a test cleared the
    tool registry) are pruned. Other kinds (provider/capability/mcp_server)
    are never touched by the sync.
    """
    # noqa: PLC0415 — lazy by design (avoids import cycles)
    from ..skills.registry import get_registry as get_skill_registry  # noqa: PLC0415
    from ..tools.builtin import register_builtin_tools  # noqa: PLC0415
    from ..tools.registry import registry as tool_registry  # noqa: PLC0415

    # Restore builtins: importing backend.tools.builtin auto-registers once,
    # but a registry.clear() (tests, hot-reload) would otherwise leave the
    # extension sync with nothing to project.
    register_builtin_tools()

    live_tools = set(tool_registry.list_all())
    for tool_name in live_tools:
        definition = tool_registry.get(tool_name)
        if definition is not None:
            extensions.register_tool_definition(definition)

    skill_registry = get_skill_registry()
    live_skills = set(skill_registry.skills.keys())
    for skill_id, skill_def in skill_registry.skills.items():
        extensions.register_skill_definition(skill_def)

    # Prune stale projections: a tool:/skill: manifest with no backing
    # definition anymore (cleared registry, removed skill pack).
    for manifest_name in extensions.list_all():
        kind = manifest_name.kind
        short = manifest_name.name.split(":", 1)[1] if ":" in manifest_name.name else ""
        if kind == ExtensionKind.TOOL and short not in live_tools:
            extensions.unregister(manifest_name.name)
        elif kind == ExtensionKind.SKILL and short not in live_skills:
            extensions.unregister(manifest_name.name)

    initialize_extensions._done = True  # type: ignore[attr-defined]
    logger.info(
        "Initialized %d extensions (%d tools, %d skills)",
        len(extensions.list_all()),
        len(tool_registry.list_all()),
        len(skill_registry.skills),
    )
    return extensions


def is_initialized() -> bool:
    """Whether :func:`initialize_extensions` has run in this process."""
    return bool(getattr(initialize_extensions, "_done", False))
