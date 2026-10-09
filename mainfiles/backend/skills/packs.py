"""
skills/packs.py — curated skill-pack system.

A pack is a bundle of related SKILL.md skills shipped with Sangam, inspired
by external skill libraries (spec-kit, archify, scientific-agent-skills,
pi). Packs live under backend/skills/packs/<name>/:

    pack.yaml               manifest: name, version, description, source
    skills/<skill>/SKILL.md one directory per skill (Claude-style frontmatter)

Packs are enabled/disabled as a unit (no file copying — the skill registry
loads enabled pack directories directly). State lives in
mainfiles/config/skills/.pack_state.json (gitignored).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

PACKS_ROOT = Path(__file__).resolve().parent / "packs"
SKILLS_CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config" / "skills"
PACK_STATE_FILE = SKILLS_CONFIG_ROOT / ".pack_state.json"


@dataclass
class SkillPack:
    name: str
    version: str = "1.0.0"
    description: str = ""
    source: str = ""  # upstream repo that inspired the pack
    skills: list[str] = field(default_factory=list)  # skill dir names
    enabled: bool = False

    @property
    def root(self) -> Path:
        return PACKS_ROOT / self.name

    @property
    def skills_root(self) -> Path:
        return self.root / "skills"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "source": self.source,
            "skills": self.skills,
            "skill_count": len(self.skills),
            "enabled": self.enabled,
        }


def _load_manifest(pack_dir: Path) -> SkillPack | None:
    manifest = pack_dir / "pack.yaml"
    if not manifest.exists():
        return None
    try:
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.warning("pack %s: bad pack.yaml: %s", pack_dir.name, exc)
        return None
    skills_dir = pack_dir / "skills"
    skill_names = []
    if skills_dir.exists():
        skill_names = sorted(
            p.name for p in skills_dir.iterdir()
            if p.is_dir() and (p / "SKILL.md").exists()
        )
    return SkillPack(
        name=str(data.get("name", pack_dir.name)),
        version=str(data.get("version", "1.0.0")),
        description=str(data.get("description", "")),
        source=str(data.get("source", "")),
        skills=data.get("skills") or skill_names,
    )


def _read_enabled() -> set[str]:
    try:
        data = json.loads(PACK_STATE_FILE.read_text(encoding="utf-8"))
        enabled = data.get("enabled", [])
        return set(enabled) if isinstance(enabled, list) else set()
    except (OSError, ValueError):
        return set()


def _write_enabled(enabled: set[str]) -> None:
    try:
        SKILLS_CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
        PACK_STATE_FILE.write_text(
            json.dumps({"enabled": sorted(enabled)}, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        logger.warning("pack state write failed: %s", exc)


def list_packs() -> list[SkillPack]:
    """All bundled packs with their enabled state."""
    enabled = _read_enabled()
    packs: list[SkillPack] = []
    if not PACKS_ROOT.exists():
        return packs
    for pack_dir in sorted(p for p in PACKS_ROOT.iterdir() if p.is_dir()):
        pack = _load_manifest(pack_dir)
        if pack is not None:
            pack.enabled = pack.name in enabled
            packs.append(pack)
    return packs


def get_pack(name: str) -> SkillPack | None:
    for pack in list_packs():
        if pack.name == name:
            return pack
    return None


def enable_pack(name: str) -> SkillPack | None:
    """Enable a pack; returns the pack, or None if unknown."""
    pack = get_pack(name)
    if pack is None:
        return None
    enabled = _read_enabled()
    enabled.add(name)
    _write_enabled(enabled)
    pack.enabled = True
    # Reload the skill registry so the pack's skills become visible.
    try:
        from .registry import reload_registry

        reload_registry()
    except Exception as exc:  # noqa: BLE001
        logger.warning("skill registry reload failed: %s", exc)
    return pack


def disable_pack(name: str) -> SkillPack | None:
    pack = get_pack(name)
    if pack is None:
        return None
    enabled = _read_enabled()
    enabled.discard(name)
    _write_enabled(enabled)
    pack.enabled = False
    try:
        from .registry import reload_registry

        reload_registry()
    except Exception as exc:  # noqa: BLE001
        logger.warning("skill registry reload failed: %s", exc)
    return pack


def enabled_pack_skill_roots() -> list[Path]:
    """Skill directories of enabled packs (fed to the skill registry)."""
    roots: list[Path] = []
    enabled = _read_enabled()
    for name in enabled:
        skills_root = PACKS_ROOT / name / "skills"
        if skills_root.exists():
            roots.append(skills_root)
    return roots


def register_pack_extensions() -> int:
    """Project packs into the unified extension registry. Returns count."""
    try:
        from ..extensions import ExtensionKind, ExtensionManifest, extensions
    except ImportError:
        return 0
    count = 0
    for pack in list_packs():
        extensions.register(
            ExtensionManifest(
                name=f"skill-pack:{pack.name}",
                version=pack.version,
                kind=ExtensionKind.SKILL,
                description=f"Skill pack: {pack.description or pack.name}",
                enabled_by_default=pack.enabled,
            )
        )
        count += 1
    return count
