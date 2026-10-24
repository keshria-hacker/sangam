"""
persona_registry.py — file-based persona registry (deep-read Wave 2,
agency-agents adapted: file-based personas + roster validation, seeded
with ~12 vetted personas, NOT 276 unvetted ones).

Layout: ``mainfiles/backend/teams/personas/<division>/<slug>.md`` with
``divisions.json`` beside them as the division taxonomy (label/icon/
color source of truth). Each persona file has YAML frontmatter:

  required: name, description, division, role, method
  optional: emoji, temperature (0..1), tags, triggers

Body sections (thin, agency-agents style): Identity / Mission / Rules /
checklist. Personas carry no tools or weights — method is the
behavioural contract (cf. council's method field).

Roster validation (CI-style, fails loudly):
* divisions.json must exist and every persona dir must be a listed
  division, and vice versa (no orphan dirs, no empty divisions);
* every file parses with all required keys, and ``division`` matches
  its parent directory;
* no duplicate persona ids (filename stems) and no duplicate methods
  (a method identifies one persona's behaviour);
* temperature, when present, in [0, 1].

``suggest_personas(task)`` reuses the skill-recommendation scoring
pattern (triggers +10, role/method words +5, tags +3, description
words +1, threshold 5) over personas instead of skills.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PERSONAS_ROOT = Path(__file__).resolve().parent / "teams" / "personas"
DIVISIONS_FILE = PERSONAS_ROOT / "divisions.json"

REQUIRED_KEYS = ("name", "description", "division", "role", "method")
OPTIONAL_KEYS = ("emoji", "temperature", "tags", "triggers")
SUGGEST_THRESHOLD = 5


@dataclass
class Persona:
    id: str  # filename stem, e.g. "coder"
    name: str
    description: str
    division: str
    role: str
    method: str
    emoji: str = ""
    temperature: float = 0.7
    tags: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    body: str = ""
    path: str = ""


def load_divisions() -> dict:
    """Division taxonomy from divisions.json (label/icon/color)."""
    try:
        data = json.loads(DIVISIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot load divisions.json: {exc}") from exc
    if not isinstance(data, dict) or not data:
        raise ValueError("divisions.json must be a non-empty object")
    return data


def _parse_persona(path: Path) -> Persona | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    try:
        _, frontmatter, body = text.split("---", 2)
        data = yaml.safe_load(frontmatter) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    temperature = data.get("temperature", 0.7)
    try:
        temperature = float(temperature)
    except (TypeError, ValueError):
        temperature = 0.7
    return Persona(
        id=path.stem,
        name=str(data.get("name", "")),
        description=str(data.get("description", "")),
        division=str(data.get("division", "")),
        role=str(data.get("role", "")),
        method=str(data.get("method", "")),
        emoji=str(data.get("emoji", "")),
        temperature=temperature,
        tags=[str(t) for t in (data.get("tags") or [])],
        triggers=[str(t) for t in (data.get("triggers") or [])],
        body=body.strip(),
        path=str(path),
    )


def load_personas(root: Path = PERSONAS_ROOT) -> dict[str, Persona]:
    """Load every teams/personas/<division>/<slug>.md file."""
    personas: dict[str, Persona] = {}
    if not root.exists():
        return personas
    for md in sorted(root.rglob("*.md")):
        if md.name == "README.md":
            continue
        persona = _parse_persona(md)
        if persona is not None:
            personas.setdefault(persona.id, persona)
    return personas


def validate_roster(root: Path = PERSONAS_ROOT) -> dict:
    """Roster-consistency validation. Returns {errors, personas, divisions}.

    Errors (any one fails the roster): unparsable persona files, missing
    required keys, division/dir mismatch, duplicate ids or methods,
    temperature out of range, empty body, divisions.json/disk drift
    (orphan dirs, listed divisions with no personas).
    """
    errors: list[str] = []
    try:
        divisions = load_divisions()
    except ValueError as exc:
        return {"errors": [str(exc)], "personas": [], "divisions": []}
    personas: dict[str, Persona] = {}
    methods: dict[str, str] = {}
    dir_divisions: set[str] = set()
    if not root.exists():
        errors.append(f"Personas root missing: {root}")
        return {"errors": errors, "personas": [], "divisions": sorted(divisions)}
    for md in sorted(root.rglob("*.md")):
        if md.name == "README.md":
            continue
        division_dir = md.parent.name
        dir_divisions.add(division_dir)
        persona = _parse_persona(md)
        if persona is None:
            errors.append(f"Unparsable persona file: {md.relative_to(root)}")
            continue
        for key in REQUIRED_KEYS:
            if not getattr(persona, key, ""):
                errors.append(f"{md.relative_to(root)}: missing required key {key!r}")
        if persona.division and persona.division != division_dir:
            errors.append(f"{md.relative_to(root)}: division {persona.division!r} "
                          f"does not match directory {division_dir!r}")
        if persona.id in personas:
            errors.append(f"Duplicate persona id: {persona.id!r}")
        else:
            personas[persona.id] = persona
        if persona.method:
            if persona.method in methods:
                errors.append(f"Duplicate method {persona.method!r}: "
                              f"{methods[persona.method]!r} and {persona.id!r}")
            else:
                methods[persona.method] = persona.id
        if not 0.0 <= persona.temperature <= 1.0:
            errors.append(f"{persona.id}: temperature {persona.temperature} out of [0, 1]")
        if not persona.body:
            errors.append(f"{persona.id}: empty body")
    for division in sorted(dir_divisions):
        if division not in divisions:
            errors.append(f"Division directory {division!r} not listed in divisions.json")
    for division in sorted(divisions):
        if division not in dir_divisions:
            errors.append(f"Division {division!r} listed in divisions.json has no personas")
    return {"errors": errors,
            "personas": sorted(personas),
            "divisions": sorted(divisions)}


def assert_roster_valid(root: Path = PERSONAS_ROOT) -> dict[str, Persona]:
    """Load the roster or raise listing every inconsistency."""
    report = validate_roster(root)
    if report["errors"]:
        raise ValueError("Persona roster invalid:\n- " + "\n- ".join(report["errors"]))
    return load_personas(root)


def suggest_personas(task: str, personas: dict[str, Persona] | None = None,
                     max_personas: int = 5) -> list[Persona]:
    """Task-based persona suggestion (skill-recommendation pattern).

    Scores task text: trigger phrase +10, role/method words +5, tags +3,
    description words (+1 each, >= 4 chars). Threshold 5, best first.
    """
    if personas is None:
        personas = load_personas()
    text = (task or "").lower()
    words = set(re.findall(r"[a-z0-9]+", text))
    scored: list[tuple[int, Persona]] = []
    for persona in personas.values():
        score = 0
        for trigger in persona.triggers:
            if trigger.lower() in text:
                score += 10
        for field_text in (persona.role, persona.method):
            for word in re.findall(r"[a-z0-9]+", field_text.lower()):
                if word in words:
                    score += 5
        for tag in persona.tags:
            tag_text = tag.lower()
            if tag_text in words or tag_text in text:
                score += 3
        desc_words = {w for w in re.findall(r"[a-z0-9]+", persona.description.lower())
                      if len(w) >= 4}
        score += len(desc_words & words)
        if score >= SUGGEST_THRESHOLD:
            scored.append((score, persona))
    scored.sort(key=lambda item: -item[0])
    return [persona for _, persona in scored[:max_personas]]
