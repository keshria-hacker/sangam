"""
pack_updates.py — skill-pack update checker (reports only, never installs).

The gap this closes: ``backend/skills/packs.py`` reports
``available_version`` as the *on-disk* ``pack.yaml`` version, so "an
update is available" could never be true — there was no remote side to
compare against. This module adds the real mechanism: compare installed
pack versions against a remote registry feed and report available
updates with version + changelog pointer.

Deliberately checker-only:
- It does NOT install, download, verify, or enable anything. Applying
  an update must reuse the existing hash-verified install path, which
  another worker owns; this module only answers "what is newer, where
  is it documented".
- It does NOT touch the skills registry or any route. The parent wires
  a route if/when one is wanted.

Feed format (JSON, ``SANGAM_PACK_FEED_URL`` env or explicit arg)::

    {"packs": {"engineering": {"version": "1.2.0",
                               "changelog_url": "https://example.com/eng/CHANGELOG.md",
                               "download_url": "https://example.com/eng-1.2.0.zip"},
               ...}}
    # or {"packs": [{"name": "engineering", "version": "1.2.0", ...}]}

``file://`` URLs are supported so tests (and offline operators) can
point at a local feed fixture without any network. HTTP(S) feeds are
fetched with urllib and a short timeout; a feed failure is reported in
the result (``feed_ok=False``), never raised to the caller as a crash,
because "cannot check" is not "no updates".

Remaining product step, recorded honestly: no feed URL is configured
in the codebase today (no remote registry exists yet). Until an
operator sets ``SANGAM_PACK_FEED_URL`` (or the parent wires a default),
``check_installed_packs()`` reports ``feed_ok=False`` with that reason
and zero updates — it does not invent a registry.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

FEED_ENV = "SANGAM_PACK_FEED_URL"
FEED_TIMEOUT_S = 10.0


def _version_parts(version: str) -> tuple:
    """Numeric version comparison: 1.10 > 1.2; non-numeric suffixes
    sort after the numeric core ('1.2rc1' < '1.2')."""
    version = (version or "0").strip().lstrip("v")
    match = re.match(r"^([0-9][0-9.]*)", version)
    core = tuple(int(p) for p in match.group(1).split(".") if p != "") if match else (0,)
    suffix = version[match.end():] if match else version
    return core, (0 if suffix == "" else -1, suffix)


def compare_versions(a: str, b: str) -> int:
    """-1 if a<b, 0 if equal, 1 if a>b."""
    ac, asuffix = _version_parts(a)
    bc, bsuffix = _version_parts(b)
    padded_a = ac + (0,) * max(0, len(bc) - len(ac))
    padded_b = bc + (0,) * max(0, len(ac) - len(bc))
    if padded_a != padded_b:
        return -1 if padded_a < padded_b else 1
    if asuffix != bsuffix:
        return -1 if asuffix < bsuffix else 1
    return 0


def is_newer(candidate: str, installed: str) -> bool:
    return compare_versions(candidate, installed) > 0


def fetch_feed(feed_url: str, timeout: float = FEED_TIMEOUT_S) -> dict:
    """Fetch and parse a feed. Raises ValueError/RuntimeError on failure
    (callers that want a soft result should use check_pack_updates)."""
    if feed_url.startswith("file://"):
        path = Path(feed_url[len("file://"):])
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"cannot read local pack feed {path}: {exc}") from exc
    else:
        req = urllib.request.Request(feed_url, headers={"User-Agent": "Sangam pack-updates/1"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise RuntimeError(f"cannot fetch pack feed {feed_url}: {exc}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"pack feed {feed_url} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"pack feed {feed_url} must be a JSON object with a 'packs' key")
    return data


def parse_feed(data: dict) -> dict[str, dict]:
    """Normalise a feed document to {pack_name: {version, changelog_url, ...}}."""
    packs = data.get("packs", {})
    out: dict[str, dict] = {}
    if isinstance(packs, dict):
        items = packs.items()
    elif isinstance(packs, list):
        items = [(entry.get("name"), entry) for entry in packs if isinstance(entry, dict)]
    else:
        return out
    for name, entry in items:
        if not name or not isinstance(entry, dict):
            continue
        out[str(name)] = {
            "version": str(entry.get("version", "")),
            "changelog_url": entry.get("changelog_url") or entry.get("changelog") or "",
            "download_url": entry.get("download_url") or entry.get("url") or "",
        }
    return out


@dataclass
class PackUpdate:
    name: str
    installed_version: str
    latest_version: str
    update_available: bool
    changelog_url: str = ""
    download_url: str = ""
    in_feed: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "installed_version": self.installed_version,
            "latest_version": self.latest_version,
            "update_available": self.update_available,
            "changelog_url": self.changelog_url,
            "download_url": self.download_url,
            "in_feed": self.in_feed,
        }


@dataclass
class PackUpdateReport:
    updates: list[PackUpdate]
    feed_url: str | None
    feed_ok: bool
    error: str = ""

    @property
    def available(self) -> list[PackUpdate]:
        return [u for u in self.updates if u.update_available]

    def to_dict(self) -> dict:
        return {
            "feed_url": self.feed_url,
            "feed_ok": self.feed_ok,
            "error": self.error,
            "packs": [u.to_dict() for u in self.updates],
            "updates_available": [u.to_dict() for u in self.available],
        }


def _installed_as_dict(installed) -> list[tuple[str, str]]:
    out = []
    for item in installed or []:
        if isinstance(item, dict):
            out.append((str(item.get("name", "")), str(item.get("version", "0"))))
        else:
            out.append((str(getattr(item, "name", "")), str(getattr(item, "version", "0"))))
    return [(n, v) for n, v in out if n]


def check_pack_updates(installed, feed_url: str | None = None) -> PackUpdateReport:
    """Compare installed packs against a feed. Never installs anything."""
    url = feed_url or os.environ.get(FEED_ENV) or None
    installed_list = _installed_as_dict(installed)
    if url is None:
        return PackUpdateReport(
            updates=[PackUpdate(n, v, v, False, in_feed=False) for n, v in installed_list],
            feed_url=None, feed_ok=False,
            error=("no pack feed configured: set SANGAM_PACK_FEED_URL to a "
                   "registry feed URL (remaining product step — no remote "
                   "registry exists in the codebase yet)"),
        )
    try:
        feed = parse_feed(fetch_feed(url))
    except (ValueError, RuntimeError) as exc:
        logger.warning("pack update check failed: %s", exc)
        return PackUpdateReport(
            updates=[PackUpdate(n, v, v, False, in_feed=False) for n, v in installed_list],
            feed_url=url, feed_ok=False, error=str(exc),
        )
    updates = []
    for name, version in installed_list:
        entry = feed.get(name)
        if entry is None or not entry["version"]:
            updates.append(PackUpdate(name, version, version, False, in_feed=False))
            continue
        latest = entry["version"]
        updates.append(PackUpdate(
            name, version, latest, is_newer(latest, version),
            changelog_url=entry["changelog_url"], download_url=entry["download_url"],
            in_feed=True,
        ))
    return PackUpdateReport(updates=updates, feed_url=url, feed_ok=True)


def check_installed_packs(feed_url: str | None = None) -> PackUpdateReport:
    """Check the packs actually installed in this Sangam checkout."""
    from .skills.packs import list_packs  # lazy: avoids import cycles at module load

    return check_pack_updates(list_packs(), feed_url=feed_url)
