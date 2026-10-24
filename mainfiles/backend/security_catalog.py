"""
security_catalog.py — Batch 2 security tool catalog: DATA ONLY.

This module never installs, downloads, or runs anything. Each entry is
a curated description: what the tool is, its risk class, and the
install command text a human may run themselves. High-risk entries
are disabled by default and need an explicit per-entry enable.

Install commands use pinned ``docker image:tag`` references where
applicable — never ``curl | bash`` — and are text only.

EXCLUSIONS (documented as data, never catalogued, never runnable
through Sangam): DDoS tooling, RATs, phishing kits, brute-force /
credential-stuffing, wireless deauth, session hijacking, backdoor /
payload-injector tooling, WAF/CAPTCHA bypass tooling.
"""
from __future__ import annotations

EXCLUSIONS = [
    "DDoS tooling",
    "RAT (remote access trojan) tooling",
    "Phishing kits",
    "Brute-force / credential-stuffing tooling",
    "Wireless deauth tooling",
    "Session-hijack tooling",
    "Backdoor / payload-injector tooling",
    "WAF / CAPTCHA bypass tooling",
]

CATALOG: list[dict] = [
    {"name": "nmap", "category": "recon", "risk": "medium",
     "description": "Network discovery and service enumeration against an allowlisted target.",
     "install": "docker pull instrumentisto/nmap:7.95",
     "enabled_by_default": True},
    {"name": "nuclei", "category": "vuln-hunter", "risk": "high",
     "description": "Template-based vulnerability scanning. High-risk: sends active probes.",
     "install": "docker pull projectdiscovery/nuclei:v3.3.0",
     "enabled_by_default": False},
    {"name": "ffuf", "category": "vuln-hunter", "risk": "high",
     "description": "Fast web fuzzer for directories and parameters. High-risk: active probing.",
     "install": "docker pull ghcr.io/ffuf/ffuf:v2.1.0",
     "enabled_by_default": False},
    {"name": "subfinder", "category": "recon", "risk": "low",
     "description": "Passive subdomain discovery for an allowlisted domain.",
     "install": "docker pull projectdiscovery/subfinder:v2.6.0",
     "enabled_by_default": True},
    {"name": "httpx", "category": "recon", "risk": "low",
     "description": "Passive HTTP probing: status, title, headers for allowlisted hosts.",
     "install": "docker pull projectdiscovery/httpx:v1.6.0",
     "enabled_by_default": True},
    {"name": "nikto", "category": "vuln-hunter", "risk": "medium",
     "description": "Web server scanner for known misconfigurations.",
     "install": "docker pull ghcr.io/sullo/nikto:2.5.0",
     "enabled_by_default": True},
    {"name": "sqlmap", "category": "vuln-hunter", "risk": "high",
     "description": "SQL injection detection. High-risk: sends active injection probes; own systems only.",
     "install": "docker pull ghcr.io/sqlmapproject/sqlmap:1.8.0",
     "enabled_by_default": False},
    {"name": "gobuster", "category": "vuln-hunter", "risk": "medium",
     "description": "Directory / DNS / vhost brute-forcing against an allowlisted target (not credentials).",
     "install": "docker pull ghcr.io/oj/gobuster:v3.6.0",
     "enabled_by_default": True},
    {"name": "zaproxy", "category": "vuln-hunter", "risk": "high",
     "description": "OWASP ZAP baseline web-app scan. High-risk: active scan traffic.",
     "install": "docker pull ghcr.io/zaproxy/zaproxy:stable-2.14.0",
     "enabled_by_default": False},
    {"name": "amass", "category": "recon", "risk": "low",
     "description": "Passive attack-surface mapping for an allowlisted domain.",
     "install": "docker pull caffix/amass:v4.2.0",
     "enabled_by_default": True},
]

_CATALOG_BY_NAME = {entry["name"]: entry for entry in CATALOG}


def catalog_entry(name: str) -> dict | None:
    return _CATALOG_BY_NAME.get((name or "").lower())


def list_catalog(enabled_overrides: dict[str, bool] | None = None) -> list[dict]:
    """Catalog entries with effective enabled state.

    ``enabled_overrides`` (from the DB settings table) wins over the
    entry default; high-risk entries default to disabled.
    """
    overrides = enabled_overrides or {}
    out = []
    for entry in CATALOG:
        item = dict(entry)
        item["enabled"] = bool(overrides.get(entry["name"], entry["enabled_by_default"]))
        out.append(item)
    return out
