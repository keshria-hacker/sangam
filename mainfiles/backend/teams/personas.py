"""
teams/personas.py — File-based persona registry (agency-agents catalog
discipline, Sangam scale: seeded, validated, never 276 unvetted).

A persona is stored like a skill definition: one Markdown file with
YAML-ish frontmatter (``name``, ``description``, ``method``,
``stance``) + a body (Identity / Mission / Rules / output format).
The registry is the set of files on disk; ``validate_personas``
fails LOUDLY on drift — missing required keys, duplicate methods
where a debate needs distinct lenses, or a registry/disk mismatch —
the exact failure mode council's validate-roster was written for.

Frontmatter parsing is deliberately small (``key: value`` lines
between ``---`` fences, stdlib only) so a persona file never needs a
YAML dependency to load.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_KEYS = ("name", "description", "method")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


@dataclass(frozen=True)
class Persona:
    slug: str
    name: str
    description: str
    method: str
    stance: str = ""
    system_prompt: str = ""
    source_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"slug": self.slug, "name": self.name, "description": self.description,
                "method": self.method, "stance": self.stance,
                "system_prompt": self.system_prompt}


def parse_persona_file(path: str | Path) -> Persona:
    """Parse one ``<slug>.md`` persona file. Raises ValueError with
    the file + missing key (loud, not a silent skip)."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if match is None:
        raise ValueError(f"{path.name}: missing --- frontmatter fence")
    raw_meta, body = match.group(1), match.group(2)
    meta: dict[str, str] = {}
    for line in raw_meta.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"').strip("'")
    missing = [k for k in REQUIRED_KEYS if not meta.get(k)]
    if missing:
        raise ValueError(f"{path.name}: missing required frontmatter keys: {', '.join(missing)}")
    return Persona(slug=path.stem, name=meta["name"], description=meta["description"],
                   method=meta["method"], stance=meta.get("stance", ""),
                   system_prompt=body.strip(), source_path=str(path))


def load_personas(directory: str | Path) -> dict[str, Persona]:
    """Load every ``*.md`` under ``directory``. A missing directory
    is an empty registry (not an error); a malformed file IS an error
    — a broken persona must fail startup/validation, not vanish."""
    directory = Path(directory)
    out: dict[str, Persona] = {}
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.md")):
        persona = parse_persona_file(path)
        if persona.slug in out:
            raise ValueError(f"duplicate persona slug: {persona.slug}")
        out[persona.slug] = persona
    return out


def validate_personas(personas: dict[str, Persona]) -> list[str]:
    """Roster validation: returns a list of problems (empty = valid).
    Checks required fields, duplicate slugs (defensive — the loader
    already rejects them), and duplicate methods within the roster,
    which would make a debate's lenses indistinguishable."""
    problems: list[str] = []
    seen_methods: dict[str, str] = {}
    for slug, persona in personas.items():
        for key in REQUIRED_KEYS:
            if not getattr(persona, key):
                problems.append(f"{slug}: missing {key}")
        if persona.method in seen_methods:
            problems.append(
                f"{slug}: duplicate method {persona.method!r} "
                f"(also {seen_methods[persona.method]})")
        else:
            seen_methods[persona.method] = slug
    return problems


def suggest_personas(task: str, personas: dict[str, Persona], limit: int = 4) -> list[Persona]:
    """Task-based persona suggestion, reusing the skill-recommendation
    pattern: keyword overlap between the task and the persona's
    description + method + stance, highest overlap first. No LLM, no
    invented ranking — an empty overlap scores 0 and is listed last."""
    words = {w.lower() for w in re.findall(r"[a-z0-9]+", task or "")}
    scored: list[tuple[int, Persona]] = []
    for persona in personas.values():
        hay = f"{persona.description} {persona.method} {persona.stance}".lower()
        hay_words = set(re.findall(r"[a-z0-9]+", hay))
        scored.append((len(words & hay_words), persona))
    scored.sort(key=lambda item: (-item[0], item[1].slug))
    return [p for _, p in scored[:limit]]
