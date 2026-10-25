"""devqa.py — Batch 12 pure helpers: ONE testing/QA system, ONE workflow
depth layer, ONE guarded security layer, ONE platform/health layer, and
ONE chat-parity layer. All functions are pure (or sqlite-backed via the
small store in devqa_routes) and deterministic; none of them claims a
live model run, a container, a VM, or an external push service.

Design rule from the brief: combine overlapping repos into single
surfaces, never one button per repo, and never fake data. Where a
source repo's headline feature is excluded by the standing guardrails
(exploit payloads, autonomous pentesting, model decensoring, a PaaS
clone, QEMU guests, Windows registry mutation), the exclusion is
recorded in EXCLUDED_CATEGORIES / docs/REPO_COVERAGE.md, not silently
dropped.
"""

from __future__ import annotations

import fnmatch
import hashlib
import ipaddress
import json
import re
import sqlite3
import uuid
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# 1. Workflow node catalogue + Dify-style app templates (langflow + dify)
# ---------------------------------------------------------------------------
# The catalogue describes the CLOSED node set the engine actually runs
# (workflows.NODE_TYPES, plus the Batch 12 human_input node). It does not
# invent node types: fan-out is already expressible as DAG edges (one node
# feeding several downstream nodes), and a sub-flow is a workflow run
# referenced by id — both are documented in the catalogue notes rather
# than added as fake executable types.

NODE_CATALOGUE: dict[str, dict] = {
    "text": {"inputs": ["template"], "outputs": ["text"],
             "desc": "Render a template with {{input.x}} / {{nodes.<id>}} placeholders."},
    "transform": {"inputs": ["op", "source?"], "outputs": ["text"],
                  "desc": "upper / lower / reverse / trim / title over a previous output."},
    "retrieve": {"inputs": ["query", "file_ids?"], "outputs": ["citations"],
                 "desc": "Hybrid retrieval over files; returns citations."},
    "memory_save": {"inputs": ["content", "kind?"], "outputs": ["memory_id"],
                    "desc": "Save templated content as a memory."},
    "http_fetch": {"inputs": ["url"], "outputs": ["text"],
                   "desc": "Fetch a public URL (SSRF-guarded), stripped text, 4000 chars."},
    "llm": {"inputs": ["prompt", "system?", "model?"], "outputs": ["text"],
            "desc": "Model call via the configured provider. Already existed (Batch 3)."},
    "agent": {"inputs": ["task", "team"], "outputs": ["team output"],
              "desc": "Run a team on a task."},
    "tool": {"inputs": ["tool", "args"], "outputs": ["tool result"],
             "desc": "Read-only tools only: web_search, code_map."},
    "code": {"inputs": ["expression", "variables?"], "outputs": ["value"],
             "desc": "Restricted expression evaluator — NOT arbitrary code."},
    "condition": {"inputs": ["left", "op", "right"], "outputs": ["branch"],
                  "desc": "Branch true/false; downstream nodes gate on run_if."},
    "loop": {"inputs": ["items", "item_template"], "outputs": ["list"],
             "desc": "Render a template per list item ({{item}} / {{item_index}})."},
    "crawl": {"inputs": ["url", "max_pages?", "max_depth?"], "outputs": ["pages"],
              "desc": "Same-host crawl, SSRF-guarded, capped pages/depth."},
    "extract": {"inputs": ["pattern? or json_path", "source?"], "outputs": ["matches"],
                "desc": "Regex named groups or a JSON path over a previous output."},
    "prompt_transform": {"inputs": ["system?", "user?", "template?"], "outputs": ["prompt parts"],
                         "desc": "Render system/user prompt parts (open-webui pipe shape, Sangam-native)."},
    "human_input": {"inputs": ["prompt", "fields?"], "outputs": ["submitted value"],
                    "desc": "Dify-style human-in-the-loop: the run pauses with status "
                           "awaiting_input until the user submits, then resumes. "
                           "Resume replays the workflow from its original input "
                           "(documented limitation: non-idempotent nodes re-run)."},
}


def node_catalogue() -> list[dict]:
    """Typed catalogue: one entry per executable node type, searchable."""
    return [{"type": t, **spec} for t, spec in NODE_CATALOGUE.items()]


WORKFLOW_TEMPLATES: dict[str, dict] = {
    "chatbot": {
        "label": "Chatbot (starter)",
        "desc": "Ask, retrieve from your files, answer with the model. A starter "
                "graph for Work — not a separate app builder.",
        "definition": {
            "nodes": [
                {"id": "ask", "type": "text", "config": {"template": "{{input.question}}"}},
                {"id": "ctx", "type": "retrieve",
                 "config": {"query": "{{nodes.ask}}", "file_ids": [], "top_k": 5}},
                {"id": "answer", "type": "llm",
                 "config": {"prompt": "Answer using this context: {{nodes.ctx}}\n\nQuestion: {{nodes.ask}}"}},
            ],
            "edges": [{"from": "ask", "to": "ctx"}, {"from": "ctx", "to": "answer"}],
        },
    },
    "agent": {
        "label": "Agent with approval (starter)",
        "desc": "Draft with the model, pause for your approval, then save. The "
                "human_input node is the approval gate — nothing saves "
                "until you submit.",
        "definition": {
            "nodes": [
                {"id": "draft", "type": "llm", "config": {"prompt": "{{input.task}}"}},
                {"id": "approve", "type": "human_input",
                 "config": {"prompt": "Approve this draft?", "fields": ["approved", "note"]}},
                {"id": "save", "type": "memory_save",
                 "config": {"content": "{{nodes.draft}}", "kind": "semantic"}},
            ],
            "edges": [{"from": "draft", "to": "approve"}, {"from": "approve", "to": "save"}],
        },
    },
    "workflow": {
        "label": "Research workflow (starter)",
        "desc": "Crawl a page you own, extract what matches, summarise with the model.",
        "definition": {
            "nodes": [
                {"id": "pages", "type": "crawl",
                 "config": {"url": "{{input.url}}", "max_pages": 5, "max_depth": 1}},
                {"id": "facts", "type": "extract",
                 "config": {"pattern": "(?P<fact>[^\\n]{10,120})"}},
                {"id": "summary", "type": "llm",
                 "config": {"prompt": "Summarise these facts: {{nodes.facts}}"}},
            ],
            "edges": [{"from": "pages", "to": "facts"}, {"from": "facts", "to": "summary"}],
        },
    },
}


def workflow_template(name: str) -> dict | None:
    tpl = WORKFLOW_TEMPLATES.get(name)
    if tpl is None:
        return None
    return {"name": name, "label": tpl["label"], "desc": tpl["desc"],
            "definition": json.loads(json.dumps(tpl["definition"]))}


# Variable-pool validation (dify variable scoping, Sangam-native).
# Allowed template roots: input.*, nodes.<known-id>.*, system.*, env.*,
# and (inside loop nodes) item / item_index. Anything else is an error
# at validation time, not a silent "" at runtime.
_TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def _walk_strings(value, out: list[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _walk_strings(v, out)
    elif isinstance(value, list):
        for v in value:
            _walk_strings(v, out)


def validate_template_variables(definition: dict) -> list[str]:
    """Return validation errors for unresolved template variables.

    Empty list = every {{...}} reference resolves to a declared scope.
    Existing engine behaviour (unknown keys render as "") is unchanged;
    this is the strict check the validate endpoint runs.
    """
    if not isinstance(definition, dict):
        return ["definition must be an object"]
    nodes = definition.get("nodes") or []
    known = {n.get("id") for n in nodes if isinstance(n, dict)}
    errors: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        strings: list[str] = []
        _walk_strings(node.get("config") or {}, strings)
        if node.get("run_if"):
            strings.append(str(node["run_if"]))
        for text in strings:
            for m in _TEMPLATE_RE.finditer(text):
                path = m.group(1)
                root = path.split(".")[0]
                if root == "input":
                    continue
                if root in ("item", "item_index"):
                    if node.get("type") != "loop":
                        errors.append(f"node {node.get('id')}: {{{{{path}}}}} "
                                      "is only valid inside a loop node")
                    continue
                if root in ("system", "env"):
                    continue
                if root == "nodes":
                    parts = path.split(".")
                    if len(parts) < 2 or parts[1] not in known:
                        errors.append(f"node {node.get('id')}: {{{{{path}}}}} "
                                      "references an unknown node")
                    continue
                errors.append(f"node {node.get('id')}: {{{{{path}}}}} "
                              "uses an unknown variable scope")
    return errors


# ---------------------------------------------------------------------------
# 2. Spec depth (spec-kit): constitution + story priority / MVP mode
# ---------------------------------------------------------------------------

def parse_constitution(text: str) -> dict:
    """Parse a constitution document: principles under '## Principles'.

    Returns {principles: [...], errors: [...]}. A constitution with no
    principles is an error — it cannot gate anything.
    """
    lines = (text or "").splitlines()
    principles: list[str] = []
    in_section = False
    for line in lines:
        if line.strip().lower().startswith("## principles"):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.strip().startswith(("- ", "* ")):
            principles.append(line.strip()[2:].strip())
    errors = [] if principles else ["constitution needs a '## Principles' section with at least one principle"]
    return {"principles": principles, "errors": errors}


def _content_words(text: str) -> set[str]:
    stop = {"the", "and", "with", "for", "must", "should", "that", "this",
            "from", "into", "over", "each", "every", "never", "always"}
    return {w.lower() for w in re.findall(r"[A-Za-z]{5,}", text or "") if w.lower() not in stop}


def constitution_check(plan: str, constitution_text: str) -> dict:
    """Heuristic constitution gate (keyword overlap, labelled as such).

    A principle counts as addressed when the plan shares at least one
    content word (5+ letters) with it. This is NOT a semantic proof —
    it catches plans that never mention a principle at all, which is
    the failure spec-kit's constitution check exists to prevent.
    """
    parsed = parse_constitution(constitution_text)
    if parsed["errors"]:
        return {"ok": False, "errors": parsed["errors"], "principles": []}
    plan_words = _content_words(plan)
    rows = []
    for principle in parsed["principles"]:
        shared = sorted(_content_words(principle) & plan_words)
        rows.append({"principle": principle, "addressed": bool(shared), "shared_words": shared})
    return {"ok": all(r["addressed"] for r in rows), "errors": [],
            "principles": rows, "method": "keyword-overlap heuristic, not semantic proof"}


def mvp_order(items: list[dict]) -> list[dict]:
    """Order tasks for an MVP run: P1 items first, dependencies respected.

    Items: [{id, priority ("P1"/"P2"/"P3"), depends_on: [ids]}].
    MVP mode runs P1 items only. Raises ValueError on a missing
    dependency, a dependency on a non-P1 item in MVP mode, or a cycle.
    """
    by_id = {t["id"]: t for t in items}
    p1 = [t for t in items if t.get("priority", "P1") == "P1"]
    p1_ids = {t["id"] for t in p1}
    for t in p1:
        for dep in t.get("depends_on") or []:
            if dep not in by_id:
                raise ValueError(f"task {t['id']} depends on unknown task {dep}")
            if dep not in p1_ids:
                raise ValueError(f"MVP mode: P1 task {t['id']} depends on non-P1 task {dep}; "
                                 "promote it to P1 or drop the dependency")
    order, done = [], set()
    remaining = list(p1)
    while remaining:
        progressed = False
        for t in list(remaining):
            if all(d in done for d in (t.get("depends_on") or [])):
                order.append(t)
                done.add(t["id"])
                remaining.remove(t)
                progressed = True
        if not progressed:
            raise ValueError(f"dependency cycle among MVP tasks: {[t['id'] for t in remaining]}")
    return order


# ---------------------------------------------------------------------------
# 3. Crawl depth (crawl4ai): strategies, scorers, filters, chunking, graph
# ---------------------------------------------------------------------------

def order_frontier(scored: list[dict], strategy: str) -> list[dict]:
    """Order a crawl frontier crawl4ai-style.

    scored: [{url, score}]. bfs keeps discovery order, dfs reverses it
    (depth-first visits the most recently discovered link first),
    best_first sorts by score descending. Unknown strategy -> ValueError.
    """
    if strategy == "bfs":
        return list(scored)
    if strategy == "dfs":
        return list(reversed(scored))
    if strategy == "best_first":
        return sorted(scored, key=lambda d: d.get("score", 0), reverse=True)
    raise ValueError(f"unknown crawl strategy: {strategy!r} (bfs | dfs | best_first)")


def score_url_depth(url: str, keywords: list[str], depth: int,
                     freshness_days: int | None = None,
                     domain_authority: float = 0.0) -> float:
    """Composite scorer: keyword + path-depth (already in crawl_job) plus
    optional freshness (newer = higher, capped at 1.0) and a caller-supplied
    domain-authority weight (Sangam has no authority index; the caller
    must supply it — never invented here)."""
    score = 0.0
    low = url.lower()
    for kw in keywords or []:
        if kw.lower() in low:
            score += 1.0
    score += max(0.0, 1.0 - 0.25 * max(0, depth - 1))  # depth 1 best, decays
    if freshness_days is not None:
        score += max(0.0, 1.0 - freshness_days / 365.0)
    score += max(0.0, min(1.0, domain_authority))
    return round(score, 3)


_CONTENT_EXTS = (".pdf", ".zip", ".exe", ".dmg", ".mp4", ".mp3", ".bin")


def apply_filters(urls: list[str], filters: list[dict], seed_host: str) -> list[str]:
    """FilterChain (crawl4ai filters.py shape): content_type excludes
    binary extensions before fetch; domain keeps same-host only;
    keyword keeps URLs containing any listed keyword. Unknown filter
    kinds are rejected, not ignored."""
    out = list(urls)
    for f in filters or []:
        kind = f.get("kind")
        if kind == "content_type":
            excluded = tuple(f.get("exclude_extensions") or _CONTENT_EXTS)
            out = [u for u in out if not urlparse(u).path.lower().endswith(excluded)]
        elif kind == "domain":
            out = [u for u in out if urlparse(u).netloc == seed_host]
        elif kind == "keyword":
            kws = [k.lower() for k in (f.get("keywords") or [])]
            out = [u for u in out if any(k in u.lower() for k in kws)]
        else:
            raise ValueError(f"unknown crawl filter kind: {kind!r}")
    return out


def chunk_markdown(markdown: str, strategy: str = "paragraph",
                   max_chars: int = 1000, overlap: int = 100) -> list[str]:
    """Markdown chunking strategies: paragraph (split on blank lines,
    re-packed to max_chars), heading (split on ATX headings), fixed
    (sliding window with overlap). Empty input -> []."""
    text = markdown or ""
    if not text.strip():
        return []
    if strategy == "heading":
        parts = re.split(r"(?m)^(?=#{1,6}\s)", text)
        chunks = [p.strip() for p in parts if p.strip()]
        return chunks or [text]
    if strategy == "fixed":
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        step = max(1, max_chars - max(0, overlap))
        return [text[i:i + max_chars] for i in range(0, len(text), step)]
    if strategy == "paragraph":
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        chunks, cur = [], ""
        for p in paras:
            if cur and len(cur) + len(p) + 2 > max_chars:
                chunks.append(cur)
                cur = p
            else:
                cur = f"{cur}\n\n{p}".strip() if cur else p
        if cur:
            chunks.append(cur)
        return chunks
    raise ValueError(f"unknown chunk strategy: {strategy!r} (paragraph | heading | fixed)")


def link_graph(pages: list[dict]) -> dict:
    """Link graph over crawled pages: nodes = page URLs, edges = links
    that point at another crawled page (external links are counted,
    not graphed, so the graph never claims coverage it lacks)."""
    nodes = {p["url"] for p in pages if p.get("url")}
    edges, external = [], 0
    for p in pages:
        for link in p.get("links") or []:
            if link in nodes:
                edges.append({"from": p["url"], "to": link})
            else:
                external += 1
    return {"nodes": sorted(nodes), "edges": edges, "external_links": external}


# ---------------------------------------------------------------------------
# 4. Guarded security depth (pentest-agents + hackingtool + strix + ECC)
# ---------------------------------------------------------------------------

EXCLUDED_CATEGORIES = {
    "ddos", "phishing_attack", "remote_administration", "post_exploitation",
    "exploit_frameworks", "anonsurf", "wireless_attack", "payload_creator",
    "waf_bypass", "credential_bruteforce", "autonomous_exploitation",
    "model_decensoring",
}
# Categories that may be catalogued, passive/detection-only on own systems:
SAFE_CATEGORIES = {
    "information_gathering", "web_attack_detection", "sqli_detection",
    "xss_detection", "forensics", "own_hash_cracking", "headers_tls_config",
}


def reject_excluded_categories(categories: list[str]) -> list[str]:
    """An import containing ANY excluded category is rejected wholesale
    (the whole import, not just the bad row) — a partial import would
    silently bless the rest."""
    return sorted(set(categories or []) & EXCLUDED_CATEGORIES)


def validate_scope_file(scope: dict) -> dict:
    """Validate a pentest-agents-style scope file.

    Shape: {domains: ["*.example.com", "example.com"], cidrs: ["10.0.0.0/8"],
    excluded: ["admin.example.com"], reason: str}. At least one domain
    or CIDR is required; bad CIDRs and bad wildcards are errors."""
    if not isinstance(scope, dict):
        raise ValueError("scope must be an object")
    domains = scope.get("domains") or []
    cidrs = scope.get("cidrs") or []
    if not domains and not cidrs:
        raise ValueError("scope needs at least one domain or CIDR")
    parsed_cidrs = []
    for c in cidrs:
        try:
            parsed_cidrs.append(ipaddress.ip_network(c, strict=False))
        except ValueError as exc:
            raise ValueError(f"invalid CIDR in scope: {c}") from exc
    for d in domains:
        if not isinstance(d, str) or not d or " " in d or d.count("*") > 1:
            raise ValueError(f"invalid scope domain: {d!r}")
    return {"domains": list(domains), "cidrs": [str(c) for c in parsed_cidrs],
            "excluded": list(scope.get("excluded") or []),
            "reason": scope.get("reason") or ""}


def scope_allows(target: str, scope: dict) -> bool:
    """Hard scope check: excluded wins, then domain wildcard or CIDR
    match. A target matching nothing is rejected (never a warning)."""
    host = urlparse(target if "://" in target else f"https://{target}").hostname or ""
    for pat in scope.get("excluded") or []:
        if fnmatch.fnmatch(host, pat):
            return False
    for pat in scope.get("domains") or []:
        if fnmatch.fnmatch(host, pat):
            return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        for c in scope.get("cidrs") or []:
            if ip in ipaddress.ip_network(c):
                return True
    return False


def finding_fingerprint(finding: dict) -> str:
    """Dedup fingerprint: normalised title + tool + target, SHA-256.
    Two findings with the same fingerprint are the same finding, however
    many times a tool re-reports it."""
    raw = "|".join([
        (finding.get("title") or "").strip().lower(),
        (finding.get("tool") or "").strip().lower(),
        (finding.get("target") or "").strip().lower(),
    ])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def dedup_findings(findings: list[dict]) -> list[dict]:
    seen, out = set(), []
    for f in findings:
        fp = finding_fingerprint(f)
        if fp in seen:
            continue
        seen.add(fp)
        out.append({**f, "fingerprint": fp})
    return out


def cvss_guard(finding: dict) -> list[str]:
    """CVSS-version guard: a finding may only be marked valid with a
    score in 0..10 and an explicit version (3.0/3.1). Missing or
    out-of-range scores block validation — they are not defaulted."""
    errors = []
    score = finding.get("cvss_score")
    if score is None:
        errors.append("cvss_score is required before validation")
    elif not isinstance(score, (int, float)) or not 0 <= score <= 10:
        errors.append(f"cvss_score must be 0..10, got {score!r}")
    if finding.get("cvss_version") not in ("3.0", "3.1"):
        errors.append("cvss_version must be '3.0' or '3.1'")
    return errors


def coverage(discovered: int, probed: int) -> dict:
    """Coverage ledger (strix): probed vs discovered, computed — never
    asserted. Zero discovered means undefined, not 100%."""
    if discovered <= 0:
        return {"discovered": 0, "probed": probed, "percent": None,
                "note": "no paths discovered yet; coverage is undefined, not 100%"}
    return {"discovered": discovered, "probed": min(probed, discovered),
            "percent": round(100.0 * min(probed, discovered) / discovered, 1)}


def sandbox_gates(docker_available: bool, allow_fallback: bool) -> dict:
    """Quickemu-style pre-flight gates, failing closed (quickemu §15):
    with Docker unavailable and fallback disallowed, an active run
    fails with docker_unavailable instead of silently running in the
    workspace. Passive recon never needs the sandbox."""
    if docker_available:
        return {"ok": True, "mode": "docker", "warning": None}
    if allow_fallback:
        return {"ok": True, "mode": "workspace-fallback",
                "warning": "Docker unavailable: running in the workspace, not isolated. "
                           "Treat results as untrusted and never run active probes this way "
                           "against anything but your own systems."}
    return {"ok": False, "mode": None, "error": "docker_unavailable",
            "detail": "Docker is unavailable and workspace fallback is disallowed for this run."}


SECURITY_PHASES = {
    "recon": ["List in-scope hosts and ports (passive only)",
              "Record headers and TLS configuration of own services",
              "Map discovered paths; coverage ledger starts here"],
    "hunt": ["Pick one class per pass: IDOR, OAuth, XSS, SQLi, info-disclosure",
             "Detection only on own systems; every probe needs its own approval",
             "No payloads aimed at bypassing a WAF or rate limit, ever"],
    "triage": ["Dedup findings by fingerprint before validating any of them",
               "CVSS guard: score + version required before 'valid'",
               "Unvalidated findings block advancing to report"],
    "report": ["Report lists only validated findings, with coverage + audit log",
               "Excluded categories are never reported as capabilities"],
}


def security_checklist(phase: str) -> list[str]:
    if phase not in SECURITY_PHASES:
        raise ValueError(f"unknown security phase: {phase!r} (recon | hunt | triage | report)")
    return list(SECURITY_PHASES[phase])


def tool_availability(entries: list[dict], probe) -> list[dict]:
    """Availability probing (hackingtool lifecycle, read-only half):
    each catalogue entry declares binary + version probe; probe(name)
    returns a path or None. Sangam never installs tools itself — a
    missing tool is shown as missing with its install hint, not
    installed silently."""
    out = []
    for e in entries:
        path = probe(e.get("binary") or e.get("name") or "")
        out.append({"name": e.get("name"), "binary": e.get("binary"),
                    "installed": path is not None, "path": path,
                    "install_hint": e.get("install_hint") or ""})
    return out


# ---------------------------------------------------------------------------
# 5. Testing/QA depth (keploy + tester-army-e2e + js-best-practices + harper)
# ---------------------------------------------------------------------------

SENSITIVE_HEADERS = {"authorization", "cookie", "x-api-key", "x-csrf-token"}


def cassette_to_pytest(cassette: dict) -> dict:
    """Keploy-inspired test generation from a recorded cassette — but
    with the safety keploy's product surface lacks in Sangam: the
    generated case is RETURNED FOR REVIEW, never written to tests/
    automatically, and any cassette carrying a sensitive header is
    rejected at generation time, not redacted after the fact.

    cassette: {name, exchanges: [{method, url, status, response_body}]}.
    Returns {test_name, code, warnings} where warnings lists the
    noise fields the replay diff will ignore (timestamps/ids)."""
    if not isinstance(cassette, dict) or not cassette.get("name"):
        raise ValueError("cassette needs a name")
    exchanges = cassette.get("exchanges") or []
    if not exchanges:
        raise ValueError("cassette has no exchanges to generate from")
    for ex in exchanges:
        headers = {k.lower(): v for k, v in (ex.get("request_headers") or {}).items()}
        bad = sorted(set(headers) & SENSITIVE_HEADERS)
        if bad:
            raise ValueError(f"cassette rejected: sensitive header(s) present: {bad} — "
                             "re-record without auth headers")
    safe = re.sub(r"[^A-Za-z0-9_]", "_", cassette["name"])[:60].strip("_") or "recorded"
    lines = [f"def test_recorded_{safe}(client, auth_headers):",
             '    """Generated from a recorded cassette — REVIEW BEFORE SAVING.',
             "    Replay diff ignores timestamp/id noise fields (see replay_diff).\"\"\""]
    for i, ex in enumerate(exchanges):
        lines.append(f"    r = client.{ex.get('method', 'GET').lower()}({ex.get('url')!r}, headers=auth_headers)")
        lines.append(f"    assert r.status_code == {ex.get('status', 200)}  # exchange {i}")
    return {"test_name": f"test_recorded_{safe}",
            "code": "\n".join(lines) + "\n",
            "review_required": True,
            "note": "Generated code is returned, not saved. Saving it to tests/ is a "
                    "separate, user-confirmed step."}


def replay_diff(recorded: dict, live: dict) -> dict:
    """Replay diff with noise stripping (cassette._strip_noise_fields
    semantics, re-implemented here so the QA surface does not depend
    on test-fixture internals): timestamp/id-like keys are ignored;
    every other difference is reported field by field."""
    noise = re.compile(r"(timestamp|_at$|_id$|^id$|csrf|token)", re.I)

    def _strip(value):
        if isinstance(value, dict):
            return {k: _strip(v) for k, v in value.items() if not noise.search(k)}
        if isinstance(value, list):
            return [_strip(v) for v in value]
        return value

    a, b = _strip(recorded), _strip(live)
    diffs = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if a.get(key) != b.get(key):
                diffs.append({"field": key, "recorded": a.get(key), "live": b.get(key)})
    elif a != b:
        diffs.append({"field": "(body)", "recorded": a, "live": b})
    return {"semantic_diffs": diffs, "match": not diffs,
            "ignored_noise_fields": "timestamp/id/token-like keys"}


# JS best-practices ruleset (goldbergyoni guide, codified as checks over
# Sangam's own frontend files — findings only, never silent rewrites).
JS_RULES = {
    "no-console-in-prod": "console.log in shipped code (use a logger or remove)",
    "no-bare-specifier": "import from a bare specifier (frontend imports must be relative)",
    "testid-for-interactive": "interactive element without data-testid (specs then depend on DOM internals)",
}


def lint_js_source(source: str, filename: str = "") -> list[dict]:
    """Lint one JS source file against the ruleset. Returns findings
    [{rule, line, quote}]; an empty list means no findings, not 'good
    code' — these are three cheap checks, not a full review."""
    findings = []
    for i, line in enumerate((source or "").splitlines(), 1):
        if re.search(r"\bconsole\.(log|debug)\b", line):
            findings.append({"rule": "no-console-in-prod", "line": i,
                             "quote": line.strip()[:120], "file": filename})
        m = re.search(r"from\s+['\"]([^.'\"/][^'\"]*)['\"]", line)
        if m:
            findings.append({"rule": "no-bare-specifier", "line": i,
                             "quote": line.strip()[:120], "file": filename})
    for m in re.finditer(r"<button(?![^>]*data-testid)", source or ""):
        line_no = (source[:m.start()]).count("\n") + 1
        findings.append({"rule": "testid-for-interactive", "line": line_no,
                         "quote": "<button ...>", "file": filename})
    return findings


# Harper-style additions to writing_lint (wired into the existing
# /quality/lint route by extending lint_text, not a second linter).
_A_AN_EXCEPTIONS = {"hour", "honest", "honour", "honor", "heir", "herb"}
_COMMON_TYPOS = {
    "teh": "the", "recieve": "receive", "adress": "address", "occured": "occurred",
    "seperate": "separate", "definately": "definitely", "neccessary": "necessary",
    "accomodate": "accommodate", "wich": "which", "thier": "their",
    "untill": "until", "goverment": "government", "enviroment": "environment",
}
_DOUBLE_COMPARATIVES = re.compile(r"\b(more|most)\s+(better|best|worse|worst|faster|fastest|bigger|biggest|smaller|smallest)\b", re.I)


def extra_writing_issues(text: str, word_iter) -> list[dict]:
    """Harper-shaped deterministic rules missing from writing_lint:
    a/an agreement, double comparatives, common typos. Each returns a
    span + suggestion, exactly like the existing rules."""
    issues = []
    words = list(word_iter)
    for j, m in enumerate(words):
        low = m.group(0).lower()
        if low in ("a", "an") and j + 1 < len(words):
            nxt = words[j + 1].group(0).lower()
            if nxt and nxt[0] in "aeiou" and nxt not in _A_AN_EXCEPTIONS and low == "a":
                issues.append({"rule": "a-an-agreement", "offset": m.start(),
                               "quote": m.group(0) + " " + words[j + 1].group(0),
                               "suggestion": f"Use 'an' before '{words[j + 1].group(0)}'."})
            elif nxt and nxt[0] not in "aeiou" and nxt not in _A_AN_EXCEPTIONS and low == "an":
                issues.append({"rule": "a-an-agreement", "offset": m.start(),
                               "quote": m.group(0) + " " + words[j + 1].group(0),
                               "suggestion": f"Use 'a' before '{words[j + 1].group(0)}'."})
        if low in _COMMON_TYPOS:
            issues.append({"rule": "common-typo", "offset": m.start(),
                           "quote": m.group(0),
                           "suggestion": f"Did you mean '{_COMMON_TYPOS[low]}'?"})
    for m in _DOUBLE_COMPARATIVES.finditer(text or ""):
        issues.append({"rule": "double-comparative", "offset": m.start(),
                       "quote": m.group(0),
                       "suggestion": "Drop 'more/most' — the comparative already carries it."})
    return issues


# Test policy (js-testing-best-practices, codified): tags + quarantine.
TEST_TAGS = {"cold": "fast, no network", "live": "needs network (opt-in via SANGAM_LIVE_NETWORK=1)",
             "quarantined": "flaky — never counted as green while quarantined"}


def classify_test(path: str, quarantined: list[str]) -> str:
    """Tag one test file: quarantined wins over live, live wins over cold."""
    name = Path(path).name
    if name in (quarantined or []):
        return "quarantined"
    if "live" in name or "network" in name:
        return "live"
    return "cold"


def suite_report(counts: dict) -> dict:
    """Suite report that refuses to call a quarantined pass green."""
    quarantined_passed = counts.get("quarantined_passed", 0)
    ok = counts.get("failed", 0) == 0 and quarantined_passed == 0
    return {"ok": ok, "counts": counts,
            "verdict": ("GREEN" if ok else
                        ("QUARANTINED-TESTS-PASSED — do not count as green"
                         if quarantined_passed else "RED"))}


# ---------------------------------------------------------------------------
# 6. Platform/health (coolify hygiene + openpanel + winutil safe half)
# ---------------------------------------------------------------------------

HEALTH_ACTIONS = {
    "clear_caches": {"risk": "low", "reversible": True,
                     "desc": "Clear Sangam-side caches (not OS files, not user data).",
                     "undo": "Caches rebuild on next use; no data is restored because none is deleted."},
    "prune_runs": {"risk": "medium", "reversible": False,
                   "desc": "Prune finished run records older than the retention window.",
                   "undo": "NOT reversible — pruned runs are gone. The audit feed records what was pruned."},
    "verify_backup": {"risk": "low", "reversible": True,
                      "desc": "Restore-dry-run: verify a backup archive opens and parses, without restoring it.",
                      "undo": "Read-only check; nothing changes."},
    "rebuild_indexes": {"risk": "low", "reversible": True,
                        "desc": "Rebuild search/memory indexes from source data.",
                        "undo": "Indexes are derived; rebuilding again restores them."},
}


def health_action_catalog() -> list[dict]:
    """Winutil catalogue shape, Sangam-safe half only: every action
    declares risk + reversibility up front. An action without a declared
    undo is refused by the route (see devqa_routes). No OS registry,
    debloat, AppX, or winget action exists here, by design."""
    return [{"id": k, **v} for k, v in HEALTH_ACTIONS.items()]


def service_status(http_code: int | None, latency_ms: float | None) -> str:
    """Classify one health probe: no response = down, 5xx = down,
    4xx = degraded (reachable but unhappy), 2xx/3xx = up."""
    if http_code is None:
        return "down"
    if http_code >= 500:
        return "down"
    if http_code >= 400:
        return "degraded"
    return "up"


def uptime_summary(checks: list[dict]) -> dict:
    """Uptime over recorded checks (SQLite rows, see devqa_routes).
    Empty history is reported as unknown — never as 100%."""
    if not checks:
        return {"checks": 0, "up": 0, "percent": None,
                "note": "no checks recorded yet; uptime is unknown"}
    up = sum(1 for c in checks if c.get("status") == "up")
    return {"checks": len(checks), "up": up,
            "percent": round(100.0 * up / len(checks), 1)}


# OpenPanel-style event taxonomy: declared events only.
EVENT_TAXONOMY: dict[str, list[str]] = {
    "chat_started": ["destination"],
    "workflow_run": ["workflow_id", "status"],
    "workflow_created": ["template?"],
    "security_run": ["phase", "status"],
    "health_action": ["action", "risk"],
    "qa_replay": ["match"],
}


def validate_event(name: str, props: dict) -> list[str]:
    """Unknown event names are rejected (dev) / logged (prod route
    returns 422 — single-user analytics must still be honest about
    what was recorded). Required props are checked; '?' props optional."""
    if name not in EVENT_TAXONOMY:
        return [f"unknown analytics event: {name!r} (declare it in EVENT_TAXONOMY first)"]
    errors = []
    for prop in EVENT_TAXONOMY[name]:
        if prop.endswith("?"):
            continue
        if prop not in (props or {}):
            errors.append(f"event {name} is missing required property {prop!r}")
    return errors


def funnel(events: list[dict], steps: list[str]) -> list[dict]:
    """Simple funnel: for each step, how many sessions reached it and
    what fraction of the previous step that is. Sessions are the
    'session' property on each event; events without one are ignored
    rather than counted as a session."""
    reached: dict[str, set] = {s: set() for s in steps}
    for e in events or []:
        if e.get("name") in reached and e.get("session"):
            reached[e["name"]].add(e["session"])
    out, prev = [], None
    for s in steps:
        n = len(reached[s])
        out.append({"step": s, "sessions": n,
                    "conversion_from_previous": (round(n / prev, 3) if prev else None)})
        prev = n if n else prev
    return out


# Gotify-shaped notification centre: webhook-in + in-app inbox only.
# No external push service is claimed (no FCM/APNs/WebPush here).
def webhook_notification(payload: dict, expected_secret: str | None) -> dict:
    """Accept a webhook notification. A configured secret must match;
    without a secret configured, webhooks are refused (an open inbox
    that anyone on the network can write to is a spam vector)."""
    if expected_secret:
        if payload.get("secret") != expected_secret:
            raise ValueError("webhook secret mismatch")
    else:
        raise ValueError("no webhook secret configured — configure one in Settings before enabling webhook-in")
    title = (payload.get("title") or "").strip()
    if not title:
        raise ValueError("webhook notification needs a title")
    return {"title": title, "body": payload.get("body") or "",
            "source": payload.get("source") or "webhook", "read": False}


# Quickemu-style VM launch PROFILES: documented external-tool configs
# only. Sangam never launches a VM, never claims a hypervisor, and the
# profile states its own prerequisite in plain language.
VM_PROFILES = [
    {"id": "ubuntu-desktop", "os": "Ubuntu Desktop",
     "tool": "quickemu (installed separately, not by Sangam)",
     "notes": "Run `quickget ubuntu` then `quickemu --vm ubuntu.conf` on a machine "
              "with QEMU installed. Sangam only stores this profile text.",
     "preflight": ["QEMU installed", "KVM available or software emulation accepted",
                   "enough disk for the guest image"]},
    {"id": "windows-11", "os": "Windows 11",
     "tool": "quickemu (installed separately, not by Sangam)",
     "notes": "Windows guests need TPM/secure-boot support in QEMU and a licensed "
              "Windows image you provide yourself. Sangam never launches a VM "
              "and never downloads or licenses an OS image for you.",
     "preflight": ["QEMU with TPM support", "licensed Windows image (yours)",
                   "enough disk for the guest image"]},
]


def vm_profiles() -> list[dict]:
    return json.loads(json.dumps(VM_PROFILES))


# Winutil safe half: READ-ONLY system checks + documented tweaks.
# Nothing here is executed by the Sangam server. The user runs a check
# on their own Windows machine; a tweak is documentation until the user
# applies it themselves, with a snapshot/undo note attached.
WINUTIL_CATALOG = [
    {"id": "win-disk-space", "kind": "check", "os": "windows",
     "desc": "Report free disk space per drive (read-only).",
     "run_by": "user on their Windows machine",
     "script": "Get-PSDrive -PSProvider FileSystem | Select-Object Name, Free, Used"},
    {"id": "win-updates-pending", "kind": "check", "os": "windows",
     "desc": "List pending Windows updates (read-only report).",
     "run_by": "user on their Windows machine",
     "script": "Get-WindowsUpdate (PSWindowsUpdate module, if installed) — report only"},
    {"id": "win-debloat", "kind": "tweak-documented-only", "os": "windows",
     "desc": "DOCUMENTED ONLY: removing preinstalled AppX apps. NOT executed by Sangam.",
     "run_by": "user, only after a system restore point",
     "script": None,
     "warning": "Destructive and hard to undo fully. Create a restore point first; "
                "Sangam will never run this for you."},
]


# ---------------------------------------------------------------------------
# 7. Chat parity (anything-llm / LibreChat / open-webui, generic shapes)
# ---------------------------------------------------------------------------
# Deliberately generic: chat folders, a prompt-template library, and
# shareable model presets. Multi-user, teams, SSO, shared chats, and
# workspaces are NOT ported (out of scope for single-user Sangam).

PROMPT_TEMPLATES = [
    {"id": "explain-simply", "title": "Explain simply",
     "prompt": "Explain this in plain language, as if to a smart non-expert. "
               "Use short paragraphs and one example."},
    {"id": "review-code", "title": "Review this code",
     "prompt": "Review the code below for bugs, security issues, and clarity. "
               "List findings with file/line references where possible, then suggest fixes."},
    {"id": "plan-task", "title": "Plan a task",
     "prompt": "Break this task into concrete steps with dependencies, in order. "
               "Flag any step that needs information I have not given you."},
    {"id": "summarise", "title": "Summarise",
     "prompt": "Summarise the text below in 5 bullets or fewer. Keep every number and name exact."},
    {"id": "brainstorm", "title": "Brainstorm",
     "prompt": "Give 10 distinct ideas for the topic below. One line each, no filler, "
               "and mark the 3 strongest with a star."},
]


def share_preset(preset: dict) -> dict:
    """Shareable model preset: a portable dict (model, system prompt,
    temperature) plus a deterministic share code. Sharing a preset
    shares NO provider keys and NO chat history — only the settings."""
    for field in ("name", "model"):
        if not preset.get(field):
            raise ValueError(f"model preset needs {field!r}")
    temp = preset.get("temperature", 0.7)
    if not isinstance(temp, (int, float)) or not 0 <= temp <= 2:
        raise ValueError("temperature must be 0..2")
    code_src = json.dumps({"model": preset["model"],
                           "system": preset.get("system") or "",
                           "temperature": temp}, sort_keys=True)
    return {"name": preset["name"], "model": preset["model"],
            "system": preset.get("system") or "", "temperature": temp,
            "share_code": hashlib.sha256(code_src.encode()).hexdigest()[:12],
            "shares_keys": False, "shares_history": False}


# ---------------------------------------------------------------------------
# 8. SQLite sidecar store (services, health history, inbox, folders, presets)
# ---------------------------------------------------------------------------
# Kept out of models.py on purpose: parallel batches share that file,
# and this store is self-contained. Tables are created on first use.
# Path override SANGAM_DEVQA_DB exists so tests never touch the real file.

def db_path() -> Path:
    import os

    override = os.environ.get("SANGAM_DEVQA_DB")
    if override:
        return Path(override)
    from ..config import settings

    return Path(settings.UPLOAD_DIR) / "devqa.db"


def ensure_store(path: Path | None = None) -> Path:
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS devqa_services (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL,
            created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS devqa_health_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, service_id TEXT NOT NULL,
            checked_at TEXT NOT NULL, status TEXT NOT NULL,
            latency_ms REAL, http_code INTEGER);
        CREATE TABLE IF NOT EXISTS devqa_notifications (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT,
            source TEXT, read INTEGER DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS devqa_folders (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, chat_ids TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS devqa_presets (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, model TEXT NOT NULL,
            system TEXT, temperature REAL, share_code TEXT);
        """)
        conn.commit()
    finally:
        conn.close()
    return path


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
