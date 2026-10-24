"""
skills/recommend.py — stack-aware skill recommendations, v2 (deep-read).

Deterministic, no model call. v1 scanned only the workspace root for 6
languages. v2 (autoskills-style, Sangam-native) scans:

* manifests at the root AND in workspace subdirectories (depth-capped,
  skip dirs) — package.json (incl. ``workspaces`` members),
  requirements.txt, pyproject.toml, Pipfile, Gemfile, go.mod,
  Cargo.toml, build.gradle, pom.xml, composer.json;
* dependency names (packages / packagePatterns), config files,
  config-file content markers, and file extensions;
* combos (e.g. react+typescript, python+fastapi) and a frontend bonus
  (any frontend tech adds the frontend-design skill).

The caller resolves "installed" from the registry. Recommended skill
names that are not installed are reported with installed=False — the
user picks each skill explicitly; there is no bulk install.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Detection table: tech id -> {packages, package_patterns, config_files,
# config_content, extensions, skills}. ``packages`` matches dependency
# names (npm/pip/cargo/gem/go-module/composer, lowercased); ``config_files``
# matches file names anywhere in the scanned tree; ``config_content``
# matches markers inside a named config file's text; ``extensions``
# matches file suffixes (language detection only, never a framework).
# ---------------------------------------------------------------------------
TECH_TABLE: dict[str, dict] = {
    "python": {
        "config_files": ["requirements.txt", "pyproject.toml", "Pipfile",
                         "setup.py", "setup.cfg"],
        "extensions": [".py"],
        "skills": ["tdd", "code-review"],
    },
    "django": {
        "packages": ["django"],
        "config_content": {"settings.py": ["django"]},
        "skills": ["tdd", "code-review"],
    },
    "fastapi": {
        "packages": ["fastapi"],
        "config_content": {},
        "skills": ["api-design", "tdd"],
    },
    "flask": {
        "packages": ["flask"],
        "skills": ["tdd", "code-review"],
    },
    "javascript": {
        "config_files": ["package.json"],
        "extensions": [".js", ".jsx", ".mjs", ".cjs"],
        "skills": ["code-review", "implement"],
    },
    "typescript": {
        "packages": ["typescript"],
        "extensions": [".ts", ".tsx"],
        "skills": ["code-review", "implement"],
    },
    "react": {
        "packages": ["react", "react-dom"],
        "skills": ["code-review", "implement"],
    },
    "nextjs": {
        "packages": ["next"],
        "config_files": ["next.config.js", "next.config.ts", "next.config.mjs"],
        "skills": ["code-review", "implement"],
    },
    "vue": {
        "packages": ["vue", "@vue/cli"],
        "config_files": ["vue.config.js"],
        "skills": ["code-review", "implement"],
    },
    "angular": {
        "packages": ["@angular/core"],
        "config_files": ["angular.json"],
        "skills": ["code-review", "implement"],
    },
    "svelte": {
        "packages": ["svelte"],
        "config_files": ["svelte.config.js"],
        "skills": ["code-review", "implement"],
    },
    "tailwind": {
        "packages": ["tailwindcss"],
        "config_files": ["tailwind.config.js", "tailwind.config.ts"],
        "skills": ["frontend-design"],
    },
    "rust": {
        "config_files": ["Cargo.toml"],
        "extensions": [".rs"],
        "skills": ["tdd", "code-review"],
    },
    "go": {
        "config_files": ["go.mod"],
        "extensions": [".go"],
        "skills": ["code-review", "implement"],
    },
    "java": {
        "config_files": ["build.gradle", "pom.xml"],
        "extensions": [".java"],
        "skills": ["tdd", "code-review"],
    },
    "ruby": {
        "config_files": ["Gemfile"],
        "extensions": [".rb"],
        "skills": ["tdd", "code-review"],
    },
    "rails": {
        "packages": ["rails"],
        "skills": ["tdd", "code-review"],
    },
    "php": {
        "config_files": ["composer.json"],
        "extensions": [".php"],
        "skills": ["code-review", "implement"],
    },
    "laravel": {
        "packages": ["laravel/framework"],
        "skills": ["code-review", "implement"],
    },
    "dotnet": {
        "package_patterns": [r"\.csproj$"],
        "extensions": [".cs"],
        "skills": ["tdd", "code-review"],
    },
}

# Backward-compatible alias: v1 name for the tech -> skill map.
STACK_SKILL_MAP: dict[str, list[str]] = {
    tech: list(spec["skills"]) for tech, spec in TECH_TABLE.items()
}

# Combos: frozenset of required techs -> extra skill names.
COMBO_SKILLS: dict[frozenset, list[str]] = {
    frozenset({"react", "typescript"}): ["react-typescript-patterns"],
    frozenset({"python", "fastapi"}): ["api-design"],
    frozenset({"react", "tailwind"}): ["frontend-design"],
    frozenset({"python", "django"}): ["django-patterns"],
}

FRONTEND_TECHS = {"react", "nextjs", "vue", "angular", "svelte", "tailwind"}
FRONTEND_BONUS_SKILLS = ["frontend-design"]

_SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__",
              "dist", "build", "target", ".tox", ".eggs", "vendor"}
_MAX_DEPTH = 2


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _iter_scanned_files(root: Path):
    """Yield (path, depth) for files under root, depth-capped, skipping dirs."""
    if not root.is_dir():
        return
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name in _SKIP_DIRS or entry.name.startswith("."):
                    if entry.name != ".github":
                        continue
                if depth < _MAX_DEPTH:
                    stack.append((entry, depth + 1))
            elif entry.is_file():
                yield entry, depth


def _collect_evidence(workspace_root: Path) -> dict:
    """Collect dep names, config file names, config texts, extensions."""
    root = Path(workspace_root)
    deps: set[str] = set()
    config_files: set[str] = set()
    extensions: set[str] = set()
    config_texts: dict[str, str] = {}
    workspace_members: list[Path] = []

    def _absorb_package_json(path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for section in ("dependencies", "devDependencies",
                        "peerDependencies", "optionalDependencies"):
            deps.update(str(k).lower() for k in (data.get(section) or {}))
        members = data.get("workspaces")
        if isinstance(members, dict):
            members = members.get("packages") or []
        if isinstance(members, list):
            for member in members:
                candidate = (path.parent / str(member).rstrip("*").rstrip("/"))
                if candidate.is_dir():
                    workspace_members.append(candidate)

    for path, _depth in _iter_scanned_files(root):
        name = path.name
        config_files.add(name)
        if path.suffix:
            extensions.add(path.suffix.lower())
        if name == "package.json":
            _absorb_package_json(path)
        elif name in ("requirements.txt", "Pipfile"):
            for line in _read_text(path).splitlines():
                line = line.strip()
                if line and not line.startswith(("#", "-")):
                    deps.add(re.split(r"[<>=!~\s;\[]", line)[0].lower())
        elif name == "pyproject.toml":
            text = _read_text(path)
            config_texts[name] = text
            for match in re.findall(r'^\s*"?([A-Za-z0-9_.\-]+)"?\s*=',
                                    text, re.M):
                deps.add(match.lower())
            for match in re.findall(r'"([A-Za-z0-9_.\-]+)(?:[<>=!~].*)?"',
                                    text):
                deps.add(match.lower())
        elif name == "Gemfile":
            for match in re.findall(r"""gem\s+['"]([^'"]+)['"]""",
                                    _read_text(path)):
                deps.add(match.lower())
        elif name == "go.mod":
            for match in re.findall(r"^\s*([a-z0-9.\-/]+)\s+v\d",
                                    _read_text(path), re.M):
                deps.add(match.lower())
        elif name == "Cargo.toml":
            for match in re.findall(r"^\s*([A-Za-z0-9_\-]+)\s*=",
                                    _read_text(path), re.M):
                deps.add(match.lower())
        elif name == "composer.json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            for section in ("require", "require-dev"):
                deps.update(str(k).lower() for k in (data.get(section) or {}))
        elif name in ("settings.py",):
            config_texts[name] = _read_text(path)

    # Workspace members: absorb their package.json deps too.
    for member in workspace_members:
        pkg = member / "package.json"
        if pkg.exists():
            _absorb_package_json(pkg)
    return {"deps": deps, "config_files": config_files,
            "extensions": extensions, "config_texts": config_texts}


def detect_stack(workspace_root: Path) -> list[str]:
    """Detect techs from manifests, configs, deps and extensions.

    v1 compatibility: a bare pyproject/requirements root still yields
    ["python"]; a package.json with a typescript dep still yields
    "typescript" (and "javascript" via its config file).
    """
    root = Path(workspace_root)
    if not root.is_dir():
        return []
    ev = _collect_evidence(root)
    deps, configs, exts = ev["deps"], ev["config_files"], ev["extensions"]
    detected: list[str] = []
    for tech, spec in TECH_TABLE.items():
        hit = False
        if any(pkg in deps for pkg in spec.get("packages", [])):
            hit = True
        if not hit and any(re.search(pat, d) for pat in
                           spec.get("package_patterns", [])
                           for d in (deps | configs)):
            hit = True
        if not hit and any(f in configs for f in spec.get("config_files", [])):
            hit = True
        if not hit:
            for cfg_name, markers in spec.get("config_content", {}).items():
                text = ev["config_texts"].get(cfg_name, "")
                if text and any(m.lower() in text.lower() for m in markers):
                    hit = True
                    break
        if not hit and tech in ("python", "javascript", "typescript", "rust",
                                "go", "java", "ruby", "php", "dotnet"):
            # Extension-only detection is language-level, never framework.
            if any(e in exts for e in spec.get("extensions", [])):
                hit = True
        if hit:
            detected.append(tech)
    # TypeScript supersedes plain JavaScript (a TS project is JS too,
    # but reporting both is noise).
    if "typescript" in detected and "javascript" in detected:
        detected.remove("javascript")
    return detected


def recommend(stack: list[str] | None = None,
              workspace_root: Path | None = None,
              installed_ids: set[str] | None = None) -> dict:
    """Return detected stack + recommended skills + installed flags.

    Extra keys vs v1: ``combos_applied`` (combo ids that fired) and
    ``frontend_bonus`` (whether the frontend bonus was added).
    """
    detected = list(stack) if stack else detect_stack(workspace_root or Path.cwd())
    detected_set = set(detected)
    seen: list[str] = []
    for tech in detected:
        for skill in TECH_TABLE.get(tech, {}).get("skills", []):
            if skill not in seen:
                seen.append(skill)
    combos_applied: list[str] = []
    for required, extra in COMBO_SKILLS.items():
        if required <= detected_set:
            combos_applied.append("+".join(sorted(required)))
            for skill in extra:
                if skill not in seen:
                    seen.append(skill)
    frontend_bonus = bool(detected_set & FRONTEND_TECHS)
    if frontend_bonus:
        for skill in FRONTEND_BONUS_SKILLS:
            if skill not in seen:
                seen.append(skill)
    installed = installed_ids or set()
    return {
        "detected_stack": detected,
        "recommended": [{"name": name, "installed": name in installed}
                        for name in seen],
        "combos_applied": combos_applied,
        "frontend_bonus": frontend_bonus,
    }
