from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "config" / "skills"


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
    source_repo: str = ""
    version: str = "1.0.0"


class SkillRegistry:
    def __init__(self, skills_root: Path = SKILLS_ROOT):
        self.root = skills_root
        self.skills: dict[str, SkillDefinition] = {}
        self._load_all()

    def _load_all(self) -> None:
        if not self.root.exists():
            return
        for skill_file in self.root.rglob("SKILL.md"):
            skill = self._parse(skill_file)
            if skill:
                self.skills[skill.id] = skill

    def _parse(self, skill_file: Path) -> SkillDefinition | None:
        try:
            content = skill_file.read_text(encoding="utf-8")
            if not content.startswith("---"):
                return None
            _, front_matter, body = content.split("---", 2)
            metadata = yaml.safe_load(front_matter) or {}
            return SkillDefinition(
                id=metadata.get("id", skill_file.parent.name),
                name=metadata.get("name", skill_file.parent.name),
                category=SkillCategory(metadata.get("category", "misc")),
                invocation=InvocationType(metadata.get("invocation", "both")),
                description=metadata.get("description", body.strip()[:200]),
                parameters=[SkillParameter(**parameter) for parameter in metadata.get("parameters", [])],
                prompt_template=body.strip(),
                dependencies=metadata.get("dependencies", []),
                tags=metadata.get("tags", []),
                source_repo=skill_file.parent.name,
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
        _registry = SkillRegistry()
    return _registry
