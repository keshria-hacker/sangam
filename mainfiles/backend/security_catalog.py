"""
security_catalog.py — Batch 2 security tool catalog: DATA ONLY (plus
execution-tier metadata added by the Wave-2 deep-read pass).

This module never installs, downloads, or runs anything itself. Each
entry is a curated description: what the tool is, its risk class, and
the install command text a human may run themselves. High-risk entries
are disabled by default and need an explicit per-entry enable.

Install commands use pinned ``docker image:tag`` references where
applicable — never ``curl | bash`` — and are text only.

EXECUTION TIERS (Wave-2): every entry now declares how (or whether)
Sangam may execute it after the existing per-run approval (which names
target + scope + tool class) and the allowlist scope check:

- ``passive`` — passive discovery only; executes directly under the
  per-run approval via the sandboxed runner (Docker when available,
  workspace fallback with its loud warning otherwise).
- ``active`` — sends active probes; executes ONLY through
  ``security_guardrails.run_isolated_command`` (Docker ``--rm`` or the
  workspace fallback, never a bare host shell), only after that same
  per-run approval, and results land in the finding store with
  validation state ``candidate`` until a human validates them.
- ``passive-only`` — cannot be gated to a safe execution in Sangam
  today, so it is NEVER executed; an approve call naming it records
  an explicit ``not_executed`` result + audit row naming the reason
  (see ``PASSIVE_ONLY_REASONS``), instead of silently widening scope.

EXCLUSIONS (documented as data, never catalogued, never runnable
through Sangam): DDoS tooling, RATs, phishing kits, brute-force /
credential-stuffing, wireless deauth, session hijacking, backdoor /
payload-injector tooling, WAF/CAPTCHA bypass tooling.
"""
from __future__ import annotations

from .security_guardrails import extract_host

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

# Execution tiers: "passive" | "active" | "passive-only".
EXECUTION_TIERS = {
    "nmap": "active",
    "nuclei": "active",
    "ffuf": "passive-only",
    "subfinder": "passive",
    "httpx": "passive",
    "nikto": "active",
    "sqlmap": "passive-only",
    "gobuster": "passive-only",
    "zaproxy": "active",
    "amass": "passive",
}

# Why a passive-only entry stays passive-only. Recorded verbatim in
# approve results and audit rows — never a silent scope widening.
PASSIVE_ONLY_REASONS = {
    "sqlmap": (
        "Active SQL-injection probes can mutate target data; Sangam has "
        "no read-only gate for them, so sqlmap stays catalogued but never "
        "executed. Run it by hand against your own system if you need it."
    ),
    "ffuf": (
        "ffuf needs a user-supplied wordlist; Sangam never invents one, "
        "so ffuf stays catalogued but never executed until a wordlist is "
        "supplied through an explicit, allowlisted path (not implemented)."
    ),
    "gobuster": (
        "gobuster dir/dns modes need a user-supplied wordlist; Sangam "
        "never invents one, so gobuster stays catalogued but never "
        "executed until a wordlist is supplied through an explicit, "
        "allowlisted path (not implemented)."
    ),
}

CATALOG: list[dict] = [
    {"name": "nmap", "category": "recon", "risk": "medium",
     "description": "Network discovery and service enumeration against an allowlisted target.",
     "install": "docker pull instrumentisto/nmap:7.95",
     "enabled_by_default": True,
     "execution_tier": "active",
     "tags": ["recon", "port-scan", "network"],
     "docker_image": "instrumentisto/nmap:7.95",
     "usage": [["Top 100 ports, service versions", "nmap -T2 -sV --top-ports 100 <host>"]],
     "lab_safe_notes": "Rate-limited (-T2). Own-systems-only; allowlist checked before execution."},
    {"name": "nuclei", "category": "vuln-hunter", "risk": "high",
     "description": "Template-based vulnerability scanning. High-risk: sends active probes.",
     "install": "docker pull projectdiscovery/nuclei:v3.3.0",
     "enabled_by_default": False,
     "execution_tier": "active",
     "tags": ["vuln-scan", "web"],
     "docker_image": "projectdiscovery/nuclei:v3.3.0",
     "usage": [["Scan a target, JSONL output", "nuclei -u <url> -silent -jsonl"]],
     "lab_safe_notes": "Active probes; enable per-entry, approve per run, own systems only."},
    {"name": "ffuf", "category": "vuln-hunter", "risk": "high",
     "description": "Fast web fuzzer for directories and parameters. High-risk: active probing.",
     "install": "docker pull ghcr.io/ffuf/ffuf:v2.1.0",
     "enabled_by_default": False,
     "execution_tier": "passive-only",
     "tags": ["vuln-scan", "web", "fuzzing"],
     "docker_image": "ghcr.io/ffuf/ffuf:v2.1.0",
     "usage": [["Fuzz directories (needs a wordlist)", "ffuf -u <url>/FUZZ -w <wordlist>"]],
     "lab_safe_notes": PASSIVE_ONLY_REASONS["ffuf"]},
    {"name": "subfinder", "category": "recon", "risk": "low",
     "description": "Passive subdomain discovery for an allowlisted domain.",
     "install": "docker pull projectdiscovery/subfinder:v2.6.0",
     "enabled_by_default": True,
     "execution_tier": "passive",
     "tags": ["recon", "dns", "subdomain"],
     "docker_image": "projectdiscovery/subfinder:v2.6.0",
     "usage": [["Passive subdomains", "subfinder -d <domain> -silent"]],
     "lab_safe_notes": "Passive only: no packets sent to the target itself."},
    {"name": "httpx", "category": "recon", "risk": "low",
     "description": "Passive HTTP probing: status, title, headers for allowlisted hosts.",
     "install": "docker pull projectdiscovery/httpx:v1.6.0",
     "enabled_by_default": True,
     "execution_tier": "passive",
     "tags": ["recon", "web", "http"],
     "docker_image": "projectdiscovery/httpx:v1.6.0",
     "usage": [["Probe one host, JSON output", "httpx -u <url> -silent -json"]],
     "lab_safe_notes": "Single HEAD/GET-style probe; no fuzzing or injection."},
    {"name": "nikto", "category": "vuln-hunter", "risk": "medium",
     "description": "Web server scanner for known misconfigurations.",
     "install": "docker pull ghcr.io/sullo/nikto:2.5.0",
     "enabled_by_default": True,
     "execution_tier": "active",
     "tags": ["vuln-scan", "web"],
     "docker_image": "ghcr.io/sullo/nikto:2.5.0",
     "usage": [["Scan a host", "nikto -h <url>"]],
     "lab_safe_notes": "Active requests against the allowlisted target only."},
    {"name": "sqlmap", "category": "vuln-hunter", "risk": "high",
     "description": "SQL injection detection. High-risk: sends active injection probes; own systems only.",
     "install": "docker pull ghcr.io/sqlmapproject/sqlmap:1.8.0",
     "enabled_by_default": False,
     "execution_tier": "passive-only",
     "tags": ["vuln-scan", "web", "sql-injection"],
     "docker_image": "ghcr.io/sqlmapproject/sqlmap:1.8.0",
     "usage": [["Assess a parameter by hand", "sqlmap -u <url> --batch"]],
     "lab_safe_notes": PASSIVE_ONLY_REASONS["sqlmap"]},
    {"name": "gobuster", "category": "vuln-hunter", "risk": "medium",
     "description": "Directory / DNS / vhost brute-forcing against an allowlisted target (not credentials).",
     "install": "docker pull ghcr.io/oj/gobuster:v3.6.0",
     "enabled_by_default": True,
     "execution_tier": "passive-only",
     "tags": ["vuln-scan", "web", "dns"],
     "docker_image": "ghcr.io/oj/gobuster:v3.6.0",
     "usage": [["Directory mode (needs a wordlist)", "gobuster dir -u <url> -w <wordlist>"]],
     "lab_safe_notes": PASSIVE_ONLY_REASONS["gobuster"]},
    {"name": "zaproxy", "category": "vuln-hunter", "risk": "high",
     "description": "OWASP ZAP baseline web-app scan. High-risk: active scan traffic.",
     "install": "docker pull ghcr.io/zaproxy/zaproxy:stable-2.14.0",
     "enabled_by_default": False,
     "execution_tier": "active",
     "tags": ["vuln-scan", "web"],
     "docker_image": "ghcr.io/zaproxy/zaproxy:stable-2.14.0",
     "usage": [["Baseline scan", "zap-baseline.py -t <url>"]],
     "lab_safe_notes": "Baseline (non-aggressive) profile only; active scan traffic, own systems only."},
    {"name": "amass", "category": "recon", "risk": "low",
     "description": "Passive attack-surface mapping for an allowlisted domain.",
     "install": "docker pull caffix/amass:v4.2.0",
     "enabled_by_default": True,
     "execution_tier": "passive",
     "tags": ["recon", "dns", "subdomain"],
     "docker_image": "caffix/amass:v4.2.0",
     "usage": [["Passive enumeration", "amass enum -passive -d <domain>"]],
     "lab_safe_notes": "Passive mode only (-passive): no direct target probing."},
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


def _target_url(target: str) -> str:
    raw = (target or "").strip()
    return raw if "://" in raw else f"https://{raw}"


def execution_command(name: str, target: str) -> list[str] | None:
    """Sandboxed argv for one catalog tool against ``target``.

    Returns None for passive-only tools (see PASSIVE_ONLY_REASONS) and
    for unknown names. The argv is a list — never a shell string — and
    is built only from the allowlisted host/URL, never from free-form
    user input beyond the already scope-checked target. Callers must
    still run it through ``run_isolated_command`` and must still have
    the per-run approval + allowlist check behind them.
    """
    entry = catalog_entry(name)
    if entry is None or entry["execution_tier"] == "passive-only":
        return None
    host = extract_host(target)
    if not host:
        return None
    url = _target_url(target)
    commands = {
        "nmap": ["nmap", "-T2", "-sV", "--top-ports", "100", host],
        "nuclei": ["nuclei", "-u", url, "-silent", "-jsonl"],
        "subfinder": ["subfinder", "-d", host, "-silent"],
        "httpx": ["httpx", "-u", url, "-silent", "-json"],
        "nikto": ["nikto", "-h", url],
        "zaproxy": ["zap-baseline.py", "-t", url],
        "amass": ["amass", "enum", "-passive", "-d", host],
    }
    return commands.get(entry["name"])


def passive_only_reason(name: str) -> str | None:
    """Reason a tool is never executed, or None when it is executable."""
    entry = catalog_entry(name)
    if entry is None:
        return "Unknown catalog tool."
    if entry["execution_tier"] != "passive-only":
        return None
    return PASSIVE_ONLY_REASONS.get(entry["name"], "No safe execution gate exists for this tool in Sangam.")
