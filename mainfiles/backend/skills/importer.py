"""
skills/importer.py — curated registry import, never auto-install
(deep-read Wave 2, autoskills distribution adapted to ask-before-act).

Flow, per skill, always in this order:

1. ``preview_curated_import(owner, repo, skill, ref)`` — fetches the
   skill directory from the upstream repo, computes a per-file SHA-256
   manifest, runs the server-side scan + authoring checks, and returns
   the preview. It writes NOTHING to the user skills root.
2. The user reviews the preview (files + hashes + scan results) and
   explicitly installs THAT ONE skill.
3. ``install_curated(preview, fetcher)`` — re-fetches, verifies every
   hash still matches the preview, then installs via verify.install_skill
   and records the upstream commit in skills-lock.json.

There is deliberately no bulk install and no ``-y`` path: a list of
skills is rejected, and install requires the exact preview the user saw.
The default fetcher reads public GitHub repos (contents API + raw
files, no auth, 15s timeout). Tests inject a fake fetcher; the fetcher
contract is ``fetcher(owner, repo, skill, ref) -> {"commit": str,
"files": {relpath: bytes}}``. Files are expected under the skill dir
itself (SKILL.md at the top, scripts/ + references/ beside it).
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

from .scan import scan_skill_dir
from .verify import (
    _write_lock,
    file_hash,
    install_skill,
    read_lock,
    run_skill_checks,
)

Fetcher = Callable[[str, str, str, str], dict]

_GITHUB_API = "https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}"
_GITHUB_RAW = "https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
_TIMEOUT_S = 15


def _validate_owner_repo_skill(owner: str, repo: str, skill: str) -> None:
    import re
    for label, value in (("owner", owner), ("repo", repo), ("skill", skill)):
        if not value or not re.fullmatch(r"[A-Za-z0-9_.\-]+", value):
            raise ValueError(f"Invalid {label}: {value!r}")


def github_fetcher(owner: str, repo: str, skill: str, ref: str) -> dict:
    """Default fetcher: public GitHub repo, skill dir at skills/<skill>/.

    Tries ``skills/<skill>`` first, then ``<skill>`` at the repo root.
    Returns {"commit": <sha or ref>, "files": {relpath: bytes}}.
    """
    _validate_owner_repo_skill(owner, repo, skill)
    for base in (f"skills/{skill}", skill):
        url = _GITHUB_API.format(owner=owner, repo=repo, path=base, ref=ref)
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                   "User-Agent": "Sangam-skills-importer"})
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                listing = json.loads(resp.read())
        except Exception:
            continue
        if not isinstance(listing, list):
            continue
        files: dict[str, bytes] = {}
        for entry in listing:
            if entry.get("type") != "file":
                continue
            raw = _GITHUB_RAW.format(owner=owner, repo=repo, ref=ref,
                                     path=entry["path"])
            with urllib.request.urlopen(
                    urllib.request.Request(raw, headers={"User-Agent": "Sangam-skills-importer"}),
                    timeout=_TIMEOUT_S) as resp:
                files[entry["name"]] = resp.read()
        if "SKILL.md" not in files:
            raise ValueError(f"Upstream dir {base} has no SKILL.md")
        return {"commit": ref, "files": files}
    raise ValueError(f"Skill {skill!r} not found in {owner}/{repo} "
                     "(tried skills/<skill>/ and <skill>/) — check owner/repo/skill")


def _materialize(files: dict[str, bytes]) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="sangam-skill-import-"))
    for rel, data in files.items():
        target = tmp / rel
        if tmp not in target.resolve().parents and target.resolve() != tmp:
            raise ValueError(f"Upstream file escapes skill dir: {rel!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return tmp


def preview_curated_import(owner: str, repo: str, skill: str, ref: str = "main",
                           fetcher: Fetcher | None = None) -> dict:
    """Dry-run preview for ONE skill. Writes nothing to the skills root."""
    _validate_owner_repo_skill(owner, repo, skill)
    fetched = (fetcher or github_fetcher)(owner, repo, skill, ref)
    files = fetched.get("files") or {}
    commit = fetched.get("commit") or ""
    if "SKILL.md" not in files:
        raise ValueError("Upstream skill has no SKILL.md; refusing preview")
    manifest = [{"path": rel,
                 "sha256": hashlib.sha256(data).hexdigest(),
                 "size": len(data)}
                for rel, data in sorted(files.items())]
    tmp = _materialize(files)
    try:
        scan = scan_skill_dir(tmp)
        checks = run_skill_checks(tmp)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return {
        "owner": owner, "repo": repo, "skill": skill, "ref": ref,
        "commit": commit, "files": manifest, "file_count": len(manifest),
        "scan": scan, "checks": checks,
        "destination": f"config/skills/{skill}",
    }


def install_curated(preview: dict, fetcher: Fetcher | None = None) -> dict:
    """Explicit per-skill Install for exactly the previewed skill.

    Re-fetches, verifies every hash against the preview, then installs
    and records the upstream commit in skills-lock.json. A preview for
    a list of skills, a hash drift, or a missing commit is refused.
    """
    if isinstance(preview, list):
        raise ValueError("Bulk install is not supported: install one skill "
                         "at a time with its own explicit preview")
    owner, repo, skill = preview["owner"], preview["repo"], preview["skill"]
    commit = preview.get("commit") or ""
    if not commit:
        raise ValueError("Cannot install without a recorded upstream commit")
    fetched = (fetcher or github_fetcher)(owner, repo, skill, preview.get("ref", "main"))
    if fetched.get("commit") and fetched["commit"] != commit:
        raise ValueError(f"Upstream commit moved since preview "
                         f"({commit} -> {fetched['commit']}); re-preview first")
    files = fetched.get("files") or {}
    expected = {f["path"]: f["sha256"] for f in preview.get("files", [])}
    for rel, sha in expected.items():
        if rel not in files:
            raise ValueError(f"Upstream file missing since preview: {rel}")
        if hashlib.sha256(files[rel]).hexdigest() != sha:
            raise ValueError(f"Upstream file changed since preview: {rel}")
    tmp = _materialize(files)
    try:
        result = install_skill(tmp, version=commit[:12] if len(commit) >= 12 else commit)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    lock = read_lock()
    entry = lock.get(result["name"]) or {}
    entry["upstream"] = {"owner": owner, "repo": repo, "skill": skill,
                         "ref": preview.get("ref", "main"), "commit": commit}
    entry["files"] = [f["path"] for f in preview.get("files", [])]
    lock[result["name"]] = entry
    _write_lock(lock)
    return {**result, "upstream": entry["upstream"]}
