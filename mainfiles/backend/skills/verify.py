"""
skills/verify.py — Batch 5: hash-verified skill installs, skills-lock.json,
per-skill checks, and pack pinning.

Install model (v1, local only — no network fetch):
  * Installing a skill copies a local source directory (a single skill dir
    or a pack dir's skill subdir) into the user skills root
    (``mainfiles/config/skills/<name>``) and records a SHA-256 hash over
    every file in the skill directory in ``skills-lock.json``
    (``{name: {version, hash, source, files}}``).
  * ``verify_lock()`` recomputes each locked hash and reports OK /
    MISMATCH / MISSING. A MISMATCH blocks script execution (403) until
    the skill is re-installed.
  * ``dry_run_install()`` lists the files + hashes that WOULD be
    installed without writing anything.

Checks (``run_skill_checks``) are static only except the optional eval:
  * frontmatter: name <= 64 chars, description <= 1024 chars, both present
  * SKILL.md markdown links must resolve to files inside the skill dir
  * scripts parse: ``python -m py_compile`` for .py, ``bash -n`` for .sh
    (no execution)
  * deterministic eval: if ``evals/*.json`` exists, each case runs its
    declared script (same interpreter allowlist as script execution)
    and its stdout must contain ``expected``; no evals/ dir -> "skipped".
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from .packs import PACKS_LOCK_FILE, PACKS_ROOT, SKILLS_CONFIG_ROOT

LOCK_FILE = SKILLS_CONFIG_ROOT / "skills-lock.json"
USER_SKILLS_ROOT = SKILLS_CONFIG_ROOT

MAX_NAME_LEN = 64
MAX_DESC_LEN = 1024
_EVAL_TIMEOUT_S = 15

# ---------------------------------------------------------------------------
# Deep-read Wave 2: skill authoring contract (anthropics format +
# mattpocock invocation contract, enforced in code, not prose).
# ---------------------------------------------------------------------------
# Closed frontmatter: only these keys may appear in SKILL.md frontmatter.
# Unknown keys fail the "frontmatter-keys" check (registry tolerance for
# unknown keys stays — tolerance at load, strictness at authoring).
ALLOWED_FRONTMATTER_KEYS = {
    "id", "name", "description", "category", "invocation",
    "model_invocation", "disable_model_invocation",
    "parameters", "tags", "triggers", "dependencies",
    "source_repo", "version", "license", "compatibility", "argument-hint",
    # Batch 10: scientific-agent-skills frontmatter contract + ego-lite
    # bootstrap. ``allowed_tools`` must be a list of tool names;
    # ``bootstrap_command`` must be a single shell-free command.
    "allowed_tools", "bootstrap_command", "last_reviewed",
}
# Anthropic guidance: SKILL.md under 500 lines; deeper material goes to
# references/ and is lazy-loaded, never pasted into the body.
MAX_SKILL_MD_LINES = 500
# AST-banned calls in skill scripts: code execution / unsafe
# deserialization primitives that must never ship in a skill script.
_BANNED_BUILTINS = {"eval", "exec"}
_BANNED_ATTRS = {("os", "system"), ("os", "popen"),
                 ("pickle", "load"), ("pickle", "loads"),
                 ("marshal", "loads")}


# ------------------------------------------------------------------ lookup
def _frontmatter_id_name(skill_md: Path) -> tuple[str | None, str | None]:
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None, None
    if not text.startswith("---"):
        return None, None
    try:
        _, fm, _ = text.split("---", 2)
        data = yaml.safe_load(fm) or {}
    except yaml.YAMLError:
        return None, None
    return data.get("id"), data.get("name")


def find_skill_dir(name: str) -> Path | None:
    """Resolve a skill name/id to its directory.

    Search order: user skills root, then every pack's skills/ dir.
    Matches directory name first, then SKILL.md frontmatter id/name.
    """
    wanted = (name or "").strip()
    if not wanted:
        return None
    candidates: list[Path] = []
    if USER_SKILLS_ROOT.exists():
        candidates.extend(p for p in USER_SKILLS_ROOT.iterdir() if p.is_dir())
    if PACKS_ROOT.exists():
        for pack_dir in PACKS_ROOT.iterdir():
            skills_root = pack_dir / "skills"
            if skills_root.exists():
                candidates.extend(p for p in skills_root.iterdir() if p.is_dir())
    for cand in candidates:
        if cand.name == wanted:
            return cand
    for cand in candidates:
        md = cand / "SKILL.md"
        if md.exists():
            sid, sname = _frontmatter_id_name(md)
            if wanted in (sid, sname):
                return cand
    return None


# ------------------------------------------------------------------ hashing
def skill_files(skill_dir: Path) -> list[Path]:
    out = []
    for p in sorted(skill_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(skill_dir)
        if "__pycache__" in rel.parts or ".git" in rel.parts:
            continue
        out.append(p)
    return out


def compute_skill_hash(skill_dir: Path) -> str:
    h = hashlib.sha256()
    for p in skill_files(skill_dir):
        rel = p.relative_to(skill_dir).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------ lockfile
def read_lock() -> dict:
    try:
        data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_lock(data: dict) -> None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def read_packs_lock() -> dict:
    try:
        data = json.loads(PACKS_LOCK_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_packs_lock(data: dict) -> None:
    PACKS_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    PACKS_LOCK_FILE.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def pin_pack(pack: str, version: str | None) -> dict:
    """Record (or clear, with version=None) a pack pin in packs-lock.json."""
    data = read_packs_lock()
    if version is None:
        data.pop(pack, None)
    else:
        data[pack] = version
    _write_packs_lock(data)
    return data


def lock_status(skill_dir: Path, name: str) -> str:
    """verified | mismatch | unlocked — for one installed skill dir."""
    lock = read_lock()
    entry = lock.get(name)
    if not entry:
        return "unlocked"
    if not skill_dir.exists():
        return "missing"
    return "verified" if compute_skill_hash(skill_dir) == entry.get("hash") else "mismatch"


def verify_lock() -> list[dict]:
    """Recompute every locked hash; one row per locked skill."""
    lock = read_lock()
    rows = []
    for name in sorted(lock):
        entry = lock[name] or {}
        skill_dir = find_skill_dir(name)
        if skill_dir is None:
            rows.append({"name": name, "status": "missing",
                         "stored_hash": entry.get("hash")})
            continue
        current = compute_skill_hash(skill_dir)
        rows.append({
            "name": name,
            "status": "ok" if current == entry.get("hash") else "mismatch",
            "stored_hash": entry.get("hash"),
            "current_hash": current,
            "source": entry.get("source"),
        })
    return rows


def assert_hash_ok(name: str) -> tuple[bool, str]:
    """True unless the skill is locked AND its hash mismatches (blocks runs)."""
    skill_dir = find_skill_dir(name)
    if skill_dir is None:
        return False, "Skill not found"
    status = lock_status(skill_dir, name)
    if status == "mismatch":
        return False, ("Skill files changed since install (hash mismatch). "
                       "Re-install the skill before running its scripts.")
    return True, ""


# ------------------------------------------------------------------ install
def dry_run_install(source: Path) -> dict:
    """Files + hashes that WOULD be installed, without writing anything."""
    source = Path(source)
    if not source.is_dir():
        raise ValueError(f"Install source not found: {source}")
    md = source / "SKILL.md"
    if not md.exists():
        raise ValueError(f"Install source has no SKILL.md: {source}")
    sid, sname = _frontmatter_id_name(md)
    name = sid or _slug(sname) or source.name
    files = [
        {"path": p.relative_to(source).as_posix(),
         "sha256": file_hash(p), "size": p.stat().st_size}
        for p in skill_files(source)
    ]
    return {"name": name, "destination": f"config/skills/{name}",
            "files": files, "file_count": len(files)}


def _slug(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def install_skill(source: Path, version: str = "1.0.0") -> dict:
    """Copy a local skill dir into the user skills root + lock its hash."""
    preview = dry_run_install(source)
    name = preview["name"]
    dest = USER_SKILLS_ROOT / name
    USER_SKILLS_ROOT.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns("__pycache__", ".git"))
    lock = read_lock()
    lock[name] = {
        "version": version,
        "hash": compute_skill_hash(dest),
        "source": str(source),
        "files": [f["path"] for f in preview["files"]],
    }
    _write_lock(lock)
    return {"name": name, "version": version, "hash": lock[name]["hash"],
            "files": preview["files"], "file_count": preview["file_count"]}


# ------------------------------------------------------------------ checks
def _parse_frontmatter(skill_dir: Path) -> tuple[dict | None, str | None]:
    md = skill_dir / "SKILL.md"
    if not md.exists():
        return None, "SKILL.md missing"
    text = md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None, "SKILL.md has no YAML frontmatter"
    try:
        _, fm, body = text.split("---", 2)
        data = yaml.safe_load(fm) or {}
    except yaml.YAMLError as exc:
        return None, f"Frontmatter YAML error: {exc}"
    return {"data": data, "body": body, "text": text}, None


def run_skill_checks(skill_dir: Path) -> dict:
    """Static checks + optional deterministic eval for one skill dir."""
    checks: list[dict] = []

    def add(name: str, status: str, detail: str = "") -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    parsed, err = _parse_frontmatter(skill_dir)
    if err:
        add("frontmatter", "failed", err)
        return {"skill": skill_dir.name, "checks": checks,
                "passed": 0, "failed": 1, "skipped": 0}
    data = parsed["data"]
    name = str(data.get("name") or "")
    desc = str(data.get("description") or "")
    if not name:
        add("frontmatter", "failed", "name missing")
    elif len(name) > MAX_NAME_LEN:
        add("frontmatter", "failed", f"name is {len(name)} chars (max {MAX_NAME_LEN})")
    elif not desc:
        add("frontmatter", "failed", "description missing")
    elif len(desc) > MAX_DESC_LEN:
        add("frontmatter", "failed", f"description is {len(desc)} chars (max {MAX_DESC_LEN})")
    else:
        add("frontmatter", "passed")

    # Link resolution: markdown links must resolve inside the skill dir.
    body = parsed["body"]
    broken = []
    for target in re.findall(r"\]\(([^)#\s]+)\)", body):
        if re.match(r"https?://|mailto:|#", target):
            continue
        resolved = (skill_dir / target).resolve()
        root = skill_dir.resolve()
        if root not in resolved.parents and resolved != root:
            broken.append(f"{target} (escapes skill dir)")
        elif not resolved.exists():
            broken.append(target)
    if broken:
        add("links", "failed", "broken links: " + ", ".join(broken))
    else:
        add("links", "passed")

    # Script parse checks (no execution).
    scripts_dir = skill_dir / "scripts"
    script_files = sorted(scripts_dir.rglob("*")) if scripts_dir.exists() else []
    # Compiled bytecode is a build artifact, not a script: py_compile
    # creates scripts/__pycache__/ on the parse check itself, so it must
    # be excluded or every second check run fails spuriously.
    script_files = [p for p in script_files
                    if p.is_file() and "__pycache__" not in p.parts
                    and p.suffix != ".pyc"]
    if not script_files:
        add("scripts-parse", "skipped", "no scripts/ dir")
    else:
        bad = []
        for p in script_files:
            if p.suffix == ".py":
                r = subprocess.run([sys.executable, "-m", "py_compile", str(p)],
                                   capture_output=True, timeout=30)
                if r.returncode != 0:
                    bad.append(p.name)
            elif p.suffix == ".sh":
                r = subprocess.run(["bash", "-n", str(p)], capture_output=True, timeout=30)
                if r.returncode != 0:
                    bad.append(p.name)
            else:
                bad.append(f"{p.name} (unsupported script type)")
        add("scripts-parse", "failed" if bad else "passed",
            ("unparsable: " + ", ".join(bad)) if bad else "")

    # Deterministic evals: evals/*.json {script, args, expected}.
    evals_dir = skill_dir / "evals"
    if not evals_dir.exists() or not list(evals_dir.glob("*.json")):
        add("eval", "skipped", "no evals/ dir")
    else:
        for case_file in sorted(evals_dir.glob("*.json")):
            try:
                case = json.loads(case_file.read_text(encoding="utf-8"))
                script = (skill_dir / case["script"]).resolve()
                root = skill_dir.resolve()
                if root not in script.parents or not script.is_file():
                    add(f"eval:{case_file.stem}", "failed", "script outside skill dir or missing")
                    continue
                cmd = ([sys.executable] if script.suffix == ".py" else
                       ["bash"] if script.suffix == ".sh" else None)
                if cmd is None:
                    add(f"eval:{case_file.stem}", "failed", "unsupported interpreter")
                    continue
                r = subprocess.run(cmd + [str(script)] + [str(a) for a in case.get("args", [])],
                                   capture_output=True, text=True, timeout=_EVAL_TIMEOUT_S)
                expected = str(case.get("expected", ""))
                if expected and expected in (r.stdout or ""):
                    add(f"eval:{case_file.stem}", "passed")
                else:
                    add(f"eval:{case_file.stem}", "failed",
                        f"expected {expected!r} in stdout, got {(r.stdout or '')[:200]!r}")
            except (ValueError, KeyError, subprocess.TimeoutExpired) as exc:
                add(f"eval:{case_file.stem}", "failed", str(exc))

    # -- Deep-read Wave 2 authoring contract checks -------------------
    # Closed frontmatter.
    unknown = sorted(set(data) - ALLOWED_FRONTMATTER_KEYS)
    if unknown:
        add("frontmatter-keys", "failed",
            "unknown frontmatter keys: " + ", ".join(unknown))
    else:
        add("frontmatter-keys", "passed")
    # 500-line SKILL.md cap (total file lines, frontmatter included).
    try:
        total_lines = len(parsed["text"].splitlines())
    except (OSError, AttributeError):
        total_lines = 0
    if total_lines > MAX_SKILL_MD_LINES:
        add("skill-md-lines", "failed",
            f"SKILL.md is {total_lines} lines (max {MAX_SKILL_MD_LINES}); "
            "move depth to references/ and lazy-load it")
    else:
        add("skill-md-lines", "passed")
    # Path-existence: bare references/scripts/assets mentions in the
    # body (outside markdown links, which the links check covers) must
    # resolve inside the skill dir.
    missing_paths = []
    for target in re.findall(r"(?:references|scripts|assets)/[^\s)'\"`]+", body):
        target = target.rstrip(".,;:")
        resolved = (skill_dir / target).resolve()
        root = skill_dir.resolve()
        if root not in resolved.parents and resolved != root:
            missing_paths.append(f"{target} (escapes skill dir)")
        elif not resolved.exists():
            missing_paths.append(target)
    if missing_paths:
        add("referenced-paths", "failed",
            "missing paths: " + ", ".join(sorted(set(missing_paths))))
    else:
        add("referenced-paths", "passed")
    # Banned-call AST scan over .py scripts.
    banned = scan_banned_calls(skill_dir)
    if banned:
        add("banned-calls", "failed",
            "; ".join(f"{b['file']}:{b['line']} {b['call']}" for b in banned))
    else:
        add("banned-calls", "passed")
    # Scripts-must-have-tests: every script must be covered by at least
    # one evals/*.json case (script field) or a tests/ file naming it.
    scripts_dir = skill_dir / "scripts"
    script_files = sorted(scripts_dir.rglob("*")) if scripts_dir.exists() else []
    # Compiled bytecode is a build artifact, not a script: py_compile
    # creates scripts/__pycache__/ on the parse check itself, so it must
    # be excluded or every second check run fails spuriously.
    script_files = [p for p in script_files
                    if p.is_file() and "__pycache__" not in p.parts
                    and p.suffix != ".pyc"]
    if not script_files:
        add("scripts-tests", "skipped", "no scripts/ dir")
    else:
        covered: set[str] = set()
        evals_dir = skill_dir / "evals"
        if evals_dir.exists():
            for case_file in evals_dir.glob("*.json"):
                try:
                    case = json.loads(case_file.read_text(encoding="utf-8"))
                    covered.add(Path(str(case.get("script", ""))).name)
                except (OSError, ValueError):
                    continue
        tests_dir = skill_dir / "tests"
        if tests_dir.exists():
            test_text = ""
            for t in tests_dir.rglob("*"):
                if t.is_file():
                    try:
                        test_text += t.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
            for p in script_files:
                if p.name in test_text:
                    covered.add(p.name)
        uncovered = [p.name for p in script_files if p.name not in covered]
        if uncovered:
            add("scripts-tests", "failed",
                "scripts without eval/test coverage: " + ", ".join(uncovered))
        else:
            add("scripts-tests", "passed")

    # -- Batch 10 authoring checks -------------------------------------
    # allowed-tools: when declared it must be a list of tool-name strings
    # (a skill declaring tools the runtime cannot offer fails here, not
    # silently at run time — scientific-agent-skills contract).
    allowed = data.get("allowed_tools")
    if allowed is None:
        add("allowed-tools", "skipped", "not declared")
    elif isinstance(allowed, list) and all(isinstance(t, str) and t.strip() for t in allowed):
        add("allowed-tools", "passed")
    else:
        add("allowed-tools", "failed",
            "allowed_tools must be a list of tool-name strings")
    # bootstrap-command: single shell-free command (bootstrap.py rules).
    bootstrap = data.get("bootstrap_command")
    if bootstrap is None:
        add("bootstrap-command", "skipped", "not declared")
    else:
        from .bootstrap import validate_bootstrap_command
        ok, reason = validate_bootstrap_command(str(bootstrap))
        add("bootstrap-command", "passed" if ok else "failed", "" if ok else reason)
    # Description word budget (anthropics "concise is key"): over ~100
    # words is a warning, not a failure — existing long descriptions
    # keep passing while new authors get the nudge.
    desc_words = len(str(data.get("description") or "").split())
    if desc_words <= 100:
        add("description-words", "passed")
    else:
        add("description-words", "warning",
            f"description is {desc_words} words (aim for <= 100); "
            "move detail into the body or references/")
    # scripts manifest: a scripts.json must list resolvable entries.
    manifest = skill_dir / "scripts.json"
    if manifest.is_file():
        try:
            from .bootstrap import declared_scripts
            entries = declared_scripts(skill_dir)
            missing = [e["name"] for e in entries if not e["exists"]]
            add("scripts-manifest", "failed" if missing else "passed",
                ("missing scripts: " + ", ".join(missing)) if missing else "")
        except ValueError as exc:
            add("scripts-manifest", "failed", str(exc))
    else:
        add("scripts-manifest", "skipped", "no scripts.json")

    passed = sum(1 for c in checks if c["status"] == "passed")
    failed = sum(1 for c in checks if c["status"] == "failed")
    skipped = sum(1 for c in checks if c["status"] == "skipped")
    return {"skill": skill_dir.name, "checks": checks,
            "passed": passed, "failed": failed, "skipped": skipped}


def scan_banned_calls(skill_dir: Path) -> list[dict]:
    """AST scan of .py scripts for banned calls.

    Flags eval/exec, os.system/os.popen, pickle/marshal loads, and any
    subprocess call with shell=True. Returns [{file, line, call}].
    Unparsable files are left to the scripts-parse check.
    """
    import ast

    findings: list[dict] = []
    scripts_dir = Path(skill_dir) / "scripts"
    if not scripts_dir.exists():
        return findings
    for path in sorted(scripts_dir.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                call_name = ""
                if isinstance(func, ast.Name):
                    call_name = func.id
                    if call_name in _BANNED_BUILTINS:
                        findings.append({"file": path.name, "line": node.lineno,
                                         "call": call_name})
                elif isinstance(func, ast.Attribute):
                    base = func.value
                    base_name = base.id if isinstance(base, ast.Name) else ""
                    call_name = f"{base_name}.{func.attr}"
                    if (base_name, func.attr) in _BANNED_ATTRS:
                        findings.append({"file": path.name, "line": node.lineno,
                                         "call": call_name})
                    elif base_name == "subprocess" and any(
                            kw.arg == "shell" and getattr(kw.value, "value", None) is True
                            for kw in node.keywords):
                        findings.append({"file": path.name, "line": node.lineno,
                                         "call": "subprocess shell=True"})
    return findings
