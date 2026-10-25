"""
memory/defense.py — Batch 9: retain-time PII/secret scan (hindsight
"Memory Defense" pattern, Sangam-native).

Runs BEFORE a fact, observation, or markdown note is stored. It never
calls a model and never invents content:

- ``allow``  — no sensitive pattern found; store as-is.
- ``redact`` — a low-severity pattern (e.g. an e-mail address) was
  found; the caller stores the redacted text and the finding list.
- ``block``  — a high-severity pattern (private key, token-like
  credential) was found; the caller must refuse the write.

Patterns reuse the vocabulary of ``contracts.redact_error_message``
(API-key/token/password shapes) plus private-key and bearer-token
shapes. This is a heuristic guard, not a guarantee: it catches
common accidental pastes, it does not prove text secret-free.
"""
from __future__ import annotations

import re

# (name, pattern, severity) — severity "block" refuses the write,
# "redact" replaces the match with [REDACTED] and lets it through.
_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "block"),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/=]{20,}"), "block"),
    ("api_key_assignment", re.compile(
        r"(?i)(api[_-]?key|secret|password|passwd|token)\s*[:=]\s*"
        r"['\"]?[A-Za-z0-9\-._~+/=]{16,}['\"]?"), "block"),
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}"), "block"),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "block"),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "redact"),
]

# Filenames that must never be packed or stored verbatim (repomix-style
# security filter, shared by the packer in backend/research/pack.py).
SECRET_FILENAME_PATTERNS: tuple[str, ...] = (
    ".env", ".env.*", "*.pem", "*.key", "id_rsa*", "id_ed25519",
    "*credentials*", "*secret*", "*.p12", "*.pfx",
)


def scan_text(text: str) -> dict:
    """Scan ``text``. Returns {action, redacted_text, findings}.

    ``findings`` is a list of {pattern, severity} — match VALUES are
    never echoed back, so a scan report cannot itself leak the secret.
    """
    findings: list[dict] = []
    redacted = text or ""
    action = "allow"
    for name, pattern, severity in _PATTERNS:
        if pattern.search(redacted):
            findings.append({"pattern": name, "severity": severity})
            if severity == "block":
                action = "block"
            elif severity == "redact":
                redacted = pattern.sub("[REDACTED]", redacted)
                if action == "allow":
                    action = "redact"
    return {"action": action, "redacted_text": redacted, "findings": findings}


def secret_filename(name: str) -> bool:
    """True when a filename looks like a credential store."""
    import fnmatch

    base = (name or "").rsplit("/", 1)[-1]
    return any(fnmatch.fnmatchcase(base, pat) or fnmatch.fnmatchcase(name, pat)
               for pat in SECRET_FILENAME_PATTERNS)
