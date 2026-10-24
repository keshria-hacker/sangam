"""
skills/recommend.py — Batch 5: stack-aware skill recommendations.

Deterministic, no model call. If no stack is given, the workspace root
(only — no recursion, read-only) is scanned for well-known manifest
files and the detected stacks are mapped through the explicit table
below to skill names. The caller resolves "installed" from the registry.
"""
from __future__ import annotations

import json
from pathlib import Path

# Explicit stack -> skill-name map (documented, deterministic).
STACK_SKILL_MAP: dict[str, list[str]] = {
    "python": ["tdd", "code-review"],
    "javascript": ["code-review", "implement"],
    "typescript": ["code-review", "implement"],
    "rust": ["tdd", "code-review"],
    "go": ["code-review", "implement"],
    "java": ["tdd", "code-review"],
}

_MANIFEST_FILES = (
    "package.json", "requirements.txt", "pyproject.toml",
    "build.gradle", "Cargo.toml", "go.mod",
)


def detect_stack(workspace_root: Path) -> list[str]:
    """Detect stacks from manifest files in the workspace root only."""
    root = Path(workspace_root)
    stacks: list[str] = []
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        stacks.append("python")
    pkg = root / "package.json"
    if pkg.exists():
        stacks.append("typescript" if _has_typescript(pkg) else "javascript")
    if (root / "Cargo.toml").exists():
        stacks.append("rust")
    if (root / "go.mod").exists():
        stacks.append("go")
    if (root / "build.gradle").exists():
        stacks.append("java")
    return stacks


def _has_typescript(pkg: Path) -> bool:
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    return "typescript" in deps


def recommend(stack: list[str] | None = None,
              workspace_root: Path | None = None,
              installed_ids: set[str] | None = None) -> dict:
    """Return detected stack + recommended skills + installed flags."""
    detected = list(stack) if stack else detect_stack(workspace_root or Path.cwd())
    seen: list[str] = []
    for s in detected:
        for skill in STACK_SKILL_MAP.get(s, []):
            if skill not in seen:
                seen.append(skill)
    installed = installed_ids or set()
    return {
        "detected_stack": detected,
        "recommended": [{"name": name, "installed": name in installed}
                        for name in seen],
    }
