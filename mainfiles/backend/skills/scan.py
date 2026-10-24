"""
skills/scan.py — Batch 5: server-side skill supply-chain / injection scan.

Scans a skill directory's SKILL.md + scripts/ for risky patterns. This
replaces reliance on the Library UI's client-side pattern match (kept
as-is in the frontend); the server scan is the authoritative one and
runs automatically on install.

Severities: high = likely exfiltration / remote execution / prompt
injection; medium = suspicious obfuscation or credential handling;
low = references to sensitive files without evidence of use.

The config audit (``audit_skill_configs``) flags plaintext-looking
secrets in skill config files but NEVER returns secret values — only
the key name + file.
"""
from __future__ import annotations

import re
from pathlib import Path

INJECTION_PHRASES = [
    "ignore previous instructions",
    "ignore all previous instructions",
    "disregard previous instructions",
    "disregard all prior instructions",
    "ignore your system prompt",
    "override your instructions",
    "you are now",
    "new system prompt",
    "do not follow your instructions",
]

# (severity, regex, message) — applied to scripts; SKILL.md gets the
# injection-phrase check plus the pipe-to-shell check.
_SCRIPT_PATTERNS: list[tuple[str, str, str]] = [
    ("high", r"curl\s+[^\n]*\|\s*(bash|sh)\b", "Downloads and pipes a remote script to a shell (curl|sh)"),
    ("high", r"wget\s+[^\n]*\|\s*(bash|sh)\b", "Downloads and pipes a remote script to a shell (wget|sh)"),
    ("high", r"(requests|urllib|httpx)\.[^\n]*(api[_-]?key|password|token|secret)", "Sends a credential over HTTP"),
    ("high", r"rm\s+-rf\s+(/|~|\$HOME)", "Destructive recursive delete of a root/home path"),
    ("medium", r"base64\.b64decode|base64\s+-d", "Base64 decoding (possible obfuscation)"),
    ("medium", r"os\.environ\[[^\]]*(KEY|TOKEN|SECRET|PASSWORD)", "Reads a secret from the environment"),
    ("medium", r"open\([\"'][^\"']*\.env[\"']", "Reads a .env file"),
    ("medium", r"(requests|urllib|httpx|curl|wget)\b", "Makes a network call from a script"),
    ("low", r"\.env|id_rsa|\.pem|credentials\.json", "References sensitive files"),
]

_LONG_B64 = re.compile(r"[A-Za-z0-9+/=]{100,}")

_SECRET_KEY = re.compile(
    r"(?i)(api[_-]?key|secret|password|passwd|auth[_-]?token|private[_-]?key)\s*[:=]\s*([\"']?)([^\s\"',}]+)"
)
_PLACEHOLDER = re.compile(r"^(xxx+|your[-_ ]|example|placeholder|changeme|\$\{.*\}|<.*>)$", re.I)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def scan_skill_dir(skill_dir: Path) -> dict:
    """Scan one skill dir; returns findings with severity + file."""
    skill_dir = Path(skill_dir)
    findings: list[dict] = []

    def add(severity: str, pattern: str, file: str, message: str) -> None:
        findings.append({"severity": severity, "pattern": pattern,
                         "file": file, "message": message})

    md = skill_dir / "SKILL.md"
    if md.exists():
        text = _read_text(md)
        lowered = text.lower()
        for phrase in INJECTION_PHRASES:
            if phrase in lowered:
                add("high", "prompt-injection", "SKILL.md",
                    f"Prompt-injection phrase in SKILL.md: {phrase!r}")
        if re.search(r"curl\s+[^\n]*\|\s*(bash|sh)\b", text) or \
                re.search(r"wget\s+[^\n]*\|\s*(bash|sh)\b", text):
            add("high", "pipe-to-shell", "SKILL.md",
                "SKILL.md instructs piping a download to a shell")
        for m in _LONG_B64.finditer(text):
            if len(m.group(0)) >= 200:
                add("medium", "base64-blob", "SKILL.md",
                    "Long base64 blob in SKILL.md (possible obfuscated payload)")
                break

    scripts_dir = skill_dir / "scripts"
    if scripts_dir.exists():
        for p in sorted(scripts_dir.rglob("*")):
            if not p.is_file():
                continue
            text = _read_text(p)
            rel = p.relative_to(skill_dir).as_posix()
            for severity, pattern, message in _SCRIPT_PATTERNS:
                if re.search(pattern, text):
                    add(severity, pattern, rel, message)
            for m in _LONG_B64.finditer(text):
                if len(m.group(0)) >= 200:
                    add("medium", "base64-blob", rel,
                        "Long base64 blob in script (possible obfuscated payload)")
                    break

    return {
        "skill": skill_dir.name,
        "findings": findings,
        "high": sum(1 for f in findings if f["severity"] == "high"),
        "medium": sum(1 for f in findings if f["severity"] == "medium"),
        "low": sum(1 for f in findings if f["severity"] == "low"),
    }


def audit_skill_configs(skill_dir: Path) -> list[dict]:
    """Flag plaintext-looking secrets in skill config files.

    Returns key name + file ONLY — never the value (redaction by design).
    """
    out: list[dict] = []
    for p in sorted(Path(skill_dir).rglob("*")):
        if not p.is_file() or p.suffix.lower() not in (".yaml", ".yml", ".json", ".toml", ".ini", ".env"):
            continue
        for m in _SECRET_KEY.finditer(_read_text(p)):
            value = m.group(3)
            if _PLACEHOLDER.match(value) or len(value) < 8:
                continue
            out.append({"key": m.group(1), "file": p.relative_to(skill_dir).as_posix(),
                        "note": "Looks like a real secret value in a skill config file; "
                                "move it to the provider-key store (value redacted)."})
            break  # one finding per file is enough
    return out
