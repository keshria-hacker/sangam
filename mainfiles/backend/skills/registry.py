from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "config" / "skills"


def _slugify(value: str) -> str:
    """Lowercase slug: runs of non-alphanumeric characters become '-'."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "skill"


def _coerce_bool(value: Any, default: bool) -> bool:
    """Coerce a frontmatter bool that may arrive as bool or string."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "on")
    return bool(value)


def _any_field(skill: Any, field_name: str, default: Any = "") -> Any:
    if isinstance(skill, dict):
        return skill.get(field_name, default)
    return getattr(skill, field_name, default)


def _skill_id(skill: Any) -> str:
    return str(_any_field(skill, "id", "") or _any_field(skill, "name", ""))


def is_model_callable(skill: Any) -> bool:
    """True when the model (or another skill) may invoke this skill.

    False for user-only skills: ``model_invocation: false``,
    ``disable_model_invocation: true``, or ``invocation: user``.
    Accepts registry SkillDefinition objects or plain dicts.
    """
    if not _coerce_bool(_any_field(skill, "model_invocation", True), True):
        return False
    if _coerce_bool(_any_field(skill, "disable_model_invocation", False), False):
        return False
    inv = str(_any_field(skill, "invocation", "both"))
    inv = inv.rsplit(".", 1)[-1].lower()
    return inv != "user"


def check_skill_call(caller_id: str, target: Any) -> tuple[bool, str]:
    """Enforce the mattpocock rule for skill-to-skill invocation.

    A skill may call a model-invoked skill (one Skill-tool call per
    target, never a bare ``/name`` mention); it may never call a
    user-only skill — the text must instead tell the user to run it.
    Returns (allowed, reason); reason is "" when allowed.
    """
    if is_model_callable(target):
        return True, ""
    return False, (
        f"Skill {caller_id!r} may not call user-only skill "
        f"{_skill_id(target)!r}: tell the user to invoke it explicitly."
    )


# ---------------------------------------------------------------------------
# Progressive disclosure (anthropics-skills) + per-run injection budget.
# ---------------------------------------------------------------------------
# Total chars of skill material a single agent-loop run may inject.
INJECTION_BUDGET_CHARS = 4000
# Per-skill description cap inside an injection (descriptions are the
# always-in-context layer, ~100 words).
INJECTION_DESCRIPTION_CHARS = 300


def progressive_injection(
    fired_skills: list[Any],
    invoked_skill_id: str | None = None,
    budget_chars: int = INJECTION_BUDGET_CHARS,
) -> dict:
    """Build the loop's skill injection under a per-run budget.

    Rules (never violated):
    * Every fired skill contributes its DESCRIPTION only (capped).
    * Exactly one skill contributes its BODY: the explicitly invoked
      skill, or — when the loop auto-fired with no explicit invocation —
      the top-ranked (first) fired skill.
    * No other body is injected, whole or truncated; lazy references
      are named as pointers only, never loaded.
    * Skill ``scripts/`` source is never included; scripts run only
      through the approval-gated path and their stdout returns as a
      tool observation (see :func:`format_script_observation`).

    Returns {text, skills: [{id, included, chars, truncated}],
    total_chars, budget_chars, invoked_id}.
    """
    fired = list(fired_skills or [])
    if not fired:
        return {"text": "", "skills": [], "total_chars": 0,
                "budget_chars": budget_chars, "invoked_id": None}
    invoked_id = invoked_skill_id
    if invoked_id is None:
        invoked_id = _skill_id(fired[0])
    # Pass 1: descriptions for every fired skill + lazy pointers for the
    # invoked skill. Pass 2: the invoked skill's body fills ONLY what is
    # left of the budget — so the total can never exceed the budget.
    chunks: list[str] = []
    rows: list[dict] = []
    body_row: dict | None = None
    body_text = ""
    for skill in fired:
        sid = _skill_id(skill)
        desc = (str(_any_field(skill, "description", "") or "")).strip()
        desc_chunk = desc[:INJECTION_DESCRIPTION_CHARS]
        header = f"## {str(_any_field(skill, 'name', sid))} (description)"
        part = f"{header}\n{desc_chunk}"
        chunks.append(part)
        row = {"id": sid, "included": "description",
               "chars": len(part),
               "truncated": len(desc) > INJECTION_DESCRIPTION_CHARS}
        if sid == invoked_id:
            body_text = (str(_any_field(skill, "prompt_template", "") or "")).strip()
            body_row = row
            refs = _any_field(skill, "reference_files", []) or []
            if refs:
                chunks.append(
                    f"Lazy references for {sid} (not loaded; request by name "
                    f"if needed): {', '.join(str(r) for r in refs)}")
        rows.append(row)
    base_text = "\n\n".join(chunks)
    if body_text and body_row is not None:
        invoked_name = next(
            (str(_any_field(s, "name", invoked_id)) for s in fired
             if _skill_id(s) == invoked_id), invoked_id)
        # Separators + header consume budget too; the body fills only
        # what is left, so the total can never exceed the budget.
        header = f"## {invoked_name} (body)\n"
        remaining = budget_chars - len(base_text) - 2 - len(header)
        if remaining > 0:
            body_chunk = body_text[:remaining]
            base_text = base_text + "\n\n" + header + body_chunk
            body_row["included"] = "description+body"
            body_row["chars"] += len(header) + len(body_chunk)
            body_row["truncated"] = body_row["truncated"] or len(body_text) > remaining
    text = base_text[:budget_chars]
    return {"text": text, "skills": rows, "total_chars": len(text),
            "budget_chars": budget_chars, "invoked_id": invoked_id}


def format_script_observation(skill_id: str, script: str, stdout: str,
                              stderr: str = "", exit_code: int = 0,
                              max_chars: int = 2000) -> str:
    """Format a skill-script run as a tool observation.

    Only stdout/stderr (truncated) are returned — the script's source is
    never pasted into context (anthropics webapp-testing black-box rule).
    """
    out = (stdout or "")[:max_chars]
    err = (stderr or "")[:500]
    parts = [f"[skill script: {skill_id}/{script} exit={exit_code}]", out]
    if err:
        parts.append(f"stderr (truncated): {err}")
    if len(stdout or "") > max_chars:
        parts.append("(stdout truncated)")
    return "\n".join(parts)


class SkillCategory(str, Enum):
    ENGINEERING = "engineering"
    PRODUCTIVITY = "productivity"
    PERSONAL = "personal"
    MISC = "misc"
    DESIGN = "design"
    BEHAVIORAL = "behavioral"
    KNOWLEDGE = "knowledge"
    SYSTEM = "system"


class InvocationType(str, Enum):
    AUTO = "auto"
    USER = "user"
    BOTH = "both"


@dataclass
class SkillParameter:
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None


@dataclass
class SkillDefinition:
    id: str
    name: str
    category: SkillCategory
    invocation: InvocationType
    description: str
    parameters: list[SkillParameter] = field(default_factory=list)
    prompt_template: str = ""
    dependencies: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    # Batch 5: declared trigger phrases for deterministic auto-invocation.
    triggers: list[str] = field(default_factory=list)
    source_repo: str = ""
    version: str = "1.0.0"
    # Deep-read Wave 2: mattpocock-style invocation contract. A skill
    # with model_invocation=False is USER-ONLY: the model (or another
    # skill) may never call it; only an explicit user act (slash
    # command, Library action) may invoke it. Frontmatter spellings:
    # ``model_invocation: false`` or ``disable_model_invocation: true``.
    model_invocation: bool = True
    # Deep-read Wave 2: progressive disclosure. ``prompt_template`` is
    # the body; ``reference_files`` names lazy references/ files under
    # the skill dir that are NEVER bulk-loaded — only named as pointers
    # until explicitly requested. ``source_dir`` is the skill dir.
    reference_files: list[str] = field(default_factory=list)
    source_dir: Path | None = None
    # Batch 10 (scientific-agent-skills frontmatter contract + ego-lite
    # bootstrap): validated fields, enforced by verify.run_skill_checks.
    # ``allowed_tools`` names tools the runtime must actually offer;
    # ``bootstrap_command`` serves the body from the tool at run time
    # (see skills/bootstrap.py — approval-gated, capped, scanned).
    allowed_tools: list[str] = field(default_factory=list)
    compatibility: str = ""
    bootstrap_command: str = ""
    last_reviewed: str = ""

    def load_reference(self, name: str) -> str:
        """Load one lazy reference file on explicit request only.

        Raises ValueError on unknown names or escapes from the skill dir.
        """
        if self.source_dir is None:
            raise ValueError(f"Skill {self.id!r} has no source dir on disk")
        if name not in self.reference_files:
            raise ValueError(f"Reference {name!r} is not declared for skill {self.id!r}")
        target = (self.source_dir / name).resolve()
        root = self.source_dir.resolve()
        if root not in target.parents and target != root:
            raise ValueError(f"Reference {name!r} escapes the skill dir")
        return target.read_text(encoding="utf-8")


class SkillRegistry:
    def __init__(
        self,
        skills_root: Path = SKILLS_ROOT,
        extra_roots: list[Path] | None = None,
    ):
        self.root = skills_root
        self.extra_roots = extra_roots or []
        self.skills: dict[str, SkillDefinition] = {}
        self._load_all()

    def _load_all(self) -> None:
        if not self.root.exists():
            return
        for skill_file in self.root.rglob("SKILL.md"):
            skill = self._parse(skill_file)
            if skill:
                self.skills[skill.id] = skill
        # Skill packs: enabled packs contribute their skill directories.
        for extra in self.extra_roots:
            if not extra.exists():
                continue
            for skill_file in extra.rglob("SKILL.md"):
                skill = self._parse(skill_file)
                if skill:
                    # Pack skills don't clobber user skills with the same id.
                    self.skills.setdefault(skill.id, skill)

    def reload(self) -> None:
        """Clear and re-load all skills from disk (picks up new SKILL.md files)."""
        self.skills.clear()
        # Re-resolve enabled packs so enable/disable takes effect.
        try:
            from .packs import enabled_pack_skill_roots

            self.extra_roots = enabled_pack_skill_roots()
        except Exception:  # noqa: BLE001 — packs are optional
            pass
        self._load_all()

    def _parse(self, skill_file: Path) -> SkillDefinition | None:
        try:
            content = skill_file.read_text(encoding="utf-8")
            if not content.startswith("---"):
                return None
            _, front_matter, body = content.split("---", 2)
            metadata = yaml.safe_load(front_matter) or {}
            # Claude-style frontmatter tolerance: `id` may be absent while
            # `name` is present (e.g. "name: my-skill"); fall back to a
            # slugified name so such files still load. Unknown keys are
            # ignored gracefully via .get() defaults below.
            raw_id = metadata.get("id") or _slugify(
                str(metadata.get("name") or skill_file.parent.name)
            )
            model_invocation = _coerce_bool(
                metadata.get("model_invocation"), default=True)
            if _coerce_bool(metadata.get("disable_model_invocation"),
                            default=False):
                model_invocation = False
            compat = metadata.get("compatibility", "")
            if isinstance(compat, list):
                compat = ", ".join(str(c) for c in compat)
            references_dir = skill_file.parent / "references"
            reference_files = (
                sorted(f"references/{p.name}" for p in references_dir.iterdir()
                       if p.is_file())
                if references_dir.is_dir() else []
            )
            return SkillDefinition(
                id=raw_id,
                name=metadata.get("name", skill_file.parent.name),
                category=SkillCategory(metadata.get("category", "misc")),
                invocation=InvocationType(metadata.get("invocation", "both")),
                description=metadata.get("description", body.strip()[:200]),
                parameters=[SkillParameter(**parameter) for parameter in metadata.get("parameters", [])],
                prompt_template=body.strip(),
                dependencies=metadata.get("dependencies", []),
                tags=metadata.get("tags", []),
                triggers=[str(t) for t in (metadata.get("triggers") or [])],
                source_repo=skill_file.parent.name,
                model_invocation=model_invocation,
                reference_files=reference_files,
                source_dir=skill_file.parent,
                allowed_tools=[str(t) for t in
                               (metadata.get("allowed_tools") or [])
                               if isinstance(t, (str, int))],
                compatibility=str(compat),
                bootstrap_command=str(metadata.get("bootstrap_command") or ""),
                last_reviewed=str(metadata.get("last_reviewed") or ""),
            )
        except (OSError, TypeError, ValueError, yaml.YAMLError):
            return None

    def get(self, skill_id: str) -> SkillDefinition | None:
        return self.skills.get(skill_id)

    def search(self, query: str) -> list[SkillDefinition]:
        normalized_query = query.lower()
        return [
            skill for skill in self.skills.values()
            if normalized_query in skill.name.lower()
            or normalized_query in skill.description.lower()
            or any(normalized_query in tag.lower() for tag in skill.tags)
        ]

    def build_prompt(self, skill_id: str, **parameters: Any) -> str:
        skill = self.get(skill_id)
        if skill is None:
            raise ValueError(f"Skill not found: {skill_id}")

        values = {parameter.name: parameter.default for parameter in skill.parameters if parameter.default is not None}
        values.update(parameters)
        missing = [parameter.name for parameter in skill.parameters if parameter.required and not values.get(parameter.name)]
        if missing:
            raise ValueError(f"Missing required parameters: {', '.join(missing)}")
        return skill.prompt_template.format(**values)

    def resolve(self, skill_id: str) -> list[SkillDefinition]:
        visited: set[str] = set()
        resolved: list[SkillDefinition] = []

        def visit(dependency_id: str) -> None:
            if dependency_id in visited:
                return
            visited.add(dependency_id)
            skill = self.get(dependency_id)
            if skill is None:
                return
            for dependency in skill.dependencies:
                visit(dependency)
            resolved.append(skill)

        visit(skill_id)
        return resolved


_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        # Enabled skill packs contribute their skill directories.
        try:
            from .packs import enabled_pack_skill_roots

            extra_roots = enabled_pack_skill_roots()
        except Exception:  # noqa: BLE001 — packs are optional
            extra_roots = []
        _registry = SkillRegistry(extra_roots=extra_roots)
    return _registry


def reload_registry() -> SkillRegistry:
    """Force a fresh reload of all skills from disk and return the registry."""
    return get_registry().reload() or get_registry()
