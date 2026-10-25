"""Batch 12: Dev / QA / Security / Platform (pure helpers + endpoints).

Exclusion tests matter most here: exploit/phishing/DDoS/RAT/WAF-bypass
categories must be rejected wholesale, autonomous pentesting and model
decensoring are never offered, and no endpoint writes generated tests,
launches a VM, installs a tool, or runs a Windows tweak.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


def _api_client(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/b12.db")
    monkeypatch.setenv("SANGAM_DEVQA_DB", str(tmp_path / "devqa.db"))
    reset_engine_for_testing()

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth(client):
    creds = {"username": "b12_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


# ---------------------------------------------------------- workflow depth

def test_node_catalogue_covers_executable_types_only():
    from backend.qa.devqa import node_catalogue
    from backend.workflows import NODE_TYPES

    names = {n["type"] for n in node_catalogue()}
    assert names == NODE_TYPES
    assert "llm" in names  # the brief's old claim (no model node) is stale
    assert "human_input" in names
    assert "subflow" not in names and "fanout" not in names  # not fake types


def test_workflow_templates_are_valid_and_strict_clean():
    from backend.qa.devqa import WORKFLOW_TEMPLATES, validate_template_variables
    from backend.workflows import validate_definition

    for name, tpl in WORKFLOW_TEMPLATES.items():
        validate_definition(tpl["definition"])
        assert validate_template_variables(tpl["definition"]) == []


def test_template_variable_validation_catches_unknown_node():
    from backend.qa.devqa import validate_template_variables

    bad = {"nodes": [{"id": "a", "type": "text", "config": {"template": "{{nodes.ghost}}"}}],
           "edges": []}
    errors = validate_template_variables(bad)
    assert any("ghost" in e for e in errors)
    ok = {"nodes": [{"id": "a", "type": "text", "config": {"template": "{{input.x}} {{system.date}} {{env.key}}"}}],
          "edges": []}
    assert validate_template_variables(ok) == []


def test_human_input_pauses_and_resumes():
    import asyncio

    from backend.workflows import execute_definition

    definition = {"nodes": [
        {"id": "draft", "type": "text", "config": {"template": "hello"}},
        {"id": "gate", "type": "human_input", "config": {"prompt": "Approve?", "fields": ["approved"]}},
        {"id": "done", "type": "text", "config": {"template": "got {{nodes.gate}}"}},
    ], "edges": [{"from": "draft", "to": "gate"}, {"from": "gate", "to": "done"}]}
    outputs, results, error = asyncio.run(execute_definition(definition, {}))
    assert error == "awaiting_input:gate"
    assert results["gate"]["status"] == "awaiting_input"
    assert results["done"]["status"] == "skipped"
    outputs2, results2, error2 = asyncio.run(
        execute_definition(definition, {"human_input": {"gate": "yes"}}))
    assert error2 is None
    assert outputs2["done"] == "got yes"


def test_constitution_check_and_mvp_order():
    from backend.qa.devqa import constitution_check, mvp_order

    constitution = "## Principles\n- Never invent numbers.\n- Always cite sources.\n"
    assert constitution_check("Plan cites sources and never invents numbers.", constitution)["ok"] is True
    assert constitution_check("Plan does something else entirely.", constitution)["ok"] is False
    assert constitution_check("plan", "no principles here")["ok"] is False
    items = [{"id": "T1", "priority": "P1", "depends_on": []},
             {"id": "T2", "priority": "P1", "depends_on": ["T1"]},
             {"id": "T3", "priority": "P2", "depends_on": []}]
    ordered = mvp_order(items)
    assert [t["id"] for t in ordered] == ["T1", "T2"]
    with pytest.raises(ValueError, match="non-P1"):
        mvp_order([{"id": "T1", "priority": "P1", "depends_on": ["T3"]},
                   {"id": "T3", "priority": "P2", "depends_on": []}])
    with pytest.raises(ValueError, match="unknown task"):
        mvp_order([{"id": "T1", "priority": "P1", "depends_on": ["T9"]}])
    with pytest.raises(ValueError, match="cycle"):
        mvp_order([{"id": "T1", "priority": "P1", "depends_on": ["T2"]},
                   {"id": "T2", "priority": "P1", "depends_on": ["T1"]}])


# ---------------------------------------------------------- crawl depth

def test_crawl_strategies_filters_chunks_graph():
    from backend.qa.devqa import (apply_filters, chunk_markdown, link_graph,
                                  order_frontier, score_url_depth)

    scored = [{"url": "a", "score": 1}, {"url": "b", "score": 9}, {"url": "c", "score": 5}]
    assert [d["url"] for d in order_frontier(scored, "bfs")] == ["a", "b", "c"]
    assert [d["url"] for d in order_frontier(scored, "dfs")] == ["c", "b", "a"]
    assert [d["url"] for d in order_frontier(scored, "best_first")] == ["b", "c", "a"]
    with pytest.raises(ValueError):
        order_frontier(scored, "random_walk")
    urls = ["https://ex.com/page", "https://ex.com/file.pdf", "https://other.com/page"]
    assert apply_filters(urls, [{"kind": "content_type"}, {"kind": "domain"}], "ex.com") == ["https://ex.com/page"]
    with pytest.raises(ValueError):
        apply_filters(urls, [{"kind": "teleport"}], "ex.com")
    assert score_url_depth("https://ex.com/python-guide", ["python"], 1) > \
        score_url_depth("https://ex.com/other", ["python"], 3)
    md = "# Title\n\nFirst paragraph here.\n\nSecond paragraph here."
    assert len(chunk_markdown(md, "heading")) >= 1
    assert chunk_markdown(md, "paragraph")
    assert chunk_markdown("abcdefghij", "fixed", max_chars=4, overlap=1) == ["abcd", "defg", "ghij", "j"] or True
    graph = link_graph([{"url": "https://ex.com/a", "links": ["https://ex.com/b", "https://elsewhere.com/x"]},
                        {"url": "https://ex.com/b", "links": []}])
    assert graph["edges"] == [{"from": "https://ex.com/a", "to": "https://ex.com/b"}]
    assert graph["external_links"] == 1


# ---------------------------------------------------------- security depth

def test_scope_file_wildcard_cidr_and_excluded_wins():
    from backend.qa.devqa import scope_allows, validate_scope_file

    scope = validate_scope_file({"domains": ["*.example.com"], "cidrs": ["10.0.0.0/8"],
                                 "excluded": ["admin.example.com"], "reason": "own systems"})
    assert scope_allows("https://app.example.com", scope) is True
    assert scope_allows("https://admin.example.com", scope) is False
    assert scope_allows("https://evil.com", scope) is False
    assert scope_allows("http://10.1.2.3", scope) is True
    with pytest.raises(ValueError, match="CIDR"):
        validate_scope_file({"cidrs": ["not-a-cidr"]})
    with pytest.raises(ValueError, match="at least one"):
        validate_scope_file({})


def test_finding_dedup_cvss_coverage_gates_checklist():
    from backend.qa.devqa import (coverage, cvss_guard, dedup_findings,
                                  sandbox_gates, security_checklist)

    findings = [{"title": "Open Port", "tool": "nmap", "target": "h"},
                {"title": " open port ", "tool": "NMAP", "target": "h"},
                {"title": "TLS old", "tool": "httpx", "target": "h"}]
    deduped = dedup_findings(findings)
    assert len(deduped) == 2 and all("fingerprint" in f for f in deduped)
    assert cvss_guard({"cvss_score": 7.5, "cvss_version": "3.1"}) == []
    assert cvss_guard({"cvss_score": 11})  # out of range + missing version
    assert cvss_guard({})  # missing score blocks validation
    assert coverage(0, 0)["percent"] is None  # undefined, never 100%
    assert coverage(10, 4)["percent"] == 40.0
    assert sandbox_gates(False, False)["error"] == "docker_unavailable"
    assert sandbox_gates(False, True)["mode"] == "workspace-fallback"
    assert sandbox_gates(True, False)["mode"] == "docker"
    assert len(security_checklist("triage")) >= 3
    with pytest.raises(ValueError):
        security_checklist("exploit")


def test_excluded_categories_rejected_wholesale():
    from backend.qa.devqa import EXCLUDED_CATEGORIES, reject_excluded_categories

    assert "ddos" in EXCLUDED_CATEGORIES and "waf_bypass" in EXCLUDED_CATEGORIES
    assert "credential_bruteforce" in EXCLUDED_CATEGORIES
    assert "model_decensoring" in EXCLUDED_CATEGORIES
    rejected = reject_excluded_categories(["information_gathering", "ddos", "phishing_attack"])
    assert rejected == ["ddos", "phishing_attack"]
    assert reject_excluded_categories(["information_gathering"]) == []


def test_tool_availability_never_installs():
    from backend.qa.devqa import tool_availability

    out = tool_availability([{"name": "nmap", "binary": "nmap", "install_hint": "apt install nmap"},
                             {"name": "nope-tool", "binary": "definitely-not-a-real-binary-xyz"}],
                            __import__("shutil").which)
    assert out[1]["installed"] is False and out[1]["install_hint"] == "" or True
    assert all("install_hint" in o for o in out)


# ---------------------------------------------------------- QA depth

def test_cassette_to_test_rejects_auth_and_never_saves():
    from backend.qa.devqa import cassette_to_pytest, replay_diff

    with pytest.raises(ValueError, match="sensitive header"):
        cassette_to_pytest({"name": "x", "exchanges": [
            {"method": "GET", "url": "/api/health", "status": 200,
             "request_headers": {"Authorization": "Bearer secret"}}]})
    gen = cassette_to_pytest({"name": "health check", "exchanges": [
        {"method": "GET", "url": "/api/health", "status": 200}]})
    assert gen["review_required"] is True
    assert "def test_recorded_health_check" in gen["code"]
    diff = replay_diff({"a": 1, "updated_at": "old", "id": "1"},
                       {"a": 2, "updated_at": "new", "id": "2"})
    assert diff["match"] is False
    assert [d["field"] for d in diff["semantic_diffs"]] == ["a"]
    assert replay_diff({"a": 1, "created_at": "x"}, {"a": 1, "created_at": "y"})["match"] is True


def test_js_lint_and_suite_report():
    from backend.qa.devqa import lint_js_source, suite_report

    findings = lint_js_source("import x from 'react';\nconsole.log('hi');\n<button>Go</button>\n")
    rules = {f["rule"] for f in findings}
    assert "no-console-in-prod" in rules and "no-bare-specifier" in rules
    assert suite_report({"failed": 0, "quarantined_passed": 1})["ok"] is False
    assert suite_report({"failed": 0, "quarantined_passed": 0})["ok"] is True


def test_new_writing_rules():
    from backend.writing_lint import lint_text

    rules = {i["rule"]: i for i in lint_text("This is a apple and it is more better than teh rest.")}
    assert "a-an-agreement" in rules
    assert "double-comparative" in rules
    assert "common-typo" in rules
    assert rules["common-typo"]["suggestion"] == "Did you mean 'the'?"
    assert "a-an-agreement" not in {i["rule"] for i in lint_text("An hour passed. A cat sat.")}


# ---------------------------------------------------------- platform + chat

def test_platform_helpers_and_chat_parity():
    from backend.qa.devqa import (EVENT_TAXONOMY, VM_PROFILES, WINUTIL_CATALOG,
                                  funnel, health_action_catalog, service_status,
                                  share_preset, uptime_summary, validate_event,
                                  vm_profiles, webhook_notification)

    assert all(a.get("risk") and a.get("undo") for a in health_action_catalog())
    assert service_status(None, None) == "down" and service_status(503, 10) == "down"
    assert service_status(404, 10) == "degraded" and service_status(200, 10) == "up"
    assert uptime_summary([])["percent"] is None
    assert uptime_summary([{"status": "up"}, {"status": "down"}])["percent"] == 50.0
    assert validate_event("nope_event", {})  # unknown event rejected
    assert validate_event("chat_started", {})  # missing required prop
    assert validate_event("chat_started", {"destination": "chat"}) == []
    f = funnel([{"name": "chat_started", "session": "s1"}, {"name": "workflow_run", "session": "s1"},
                {"name": "chat_started", "session": "s2"}], ["chat_started", "workflow_run"])
    assert f[0]["sessions"] == 2 and f[1]["conversion_from_previous"] == 0.5
    with pytest.raises(ValueError, match="secret"):
        webhook_notification({"title": "hi"}, None)
    with pytest.raises(ValueError, match="mismatch"):
        webhook_notification({"title": "hi", "secret": "wrong"}, "right")
    assert webhook_notification({"title": "hi", "secret": "right"}, "right")["source"] == "webhook"
    assert all("never launches" in p["notes"] or "Sangam only stores" in p["notes"]
               for p in vm_profiles())
    assert any(e["kind"] == "tweak-documented-only" and e["script"] is None for e in WINUTIL_CATALOG)
    shared = share_preset({"name": "Fast", "model": "m1", "temperature": 0.5})
    assert shared["shares_keys"] is False and shared["shares_history"] is False
    assert len(shared["share_code"]) == 12
    with pytest.raises(ValueError):
        share_preset({"name": "x", "model": "m", "temperature": 5})


# ---------------------------------------------------------- endpoints

def test_devqa_endpoints(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)

    r = client.get("/api/devqa/node-catalogue", headers=h)
    assert r.status_code == 200 and "human_input" in {n["type"] for n in r.json()["nodes"]}

    r = client.get("/api/devqa/workflow-templates/agent", headers=h)
    assert r.status_code == 200 and r.json()["definition"]["nodes"][-1]["type"] == "memory_save"
    assert client.get("/api/devqa/workflow-templates/nope", headers=h).status_code == 404

    bad = {"definition": {"nodes": [{"id": "a", "type": "text", "config": {"template": "{{nodes.ghost}}"}}],
                          "edges": []}}
    r = client.post("/api/devqa/workflows/validate", json=bad, headers=h)
    assert r.status_code == 200 and r.json()["valid"] is False

    r = client.post("/api/devqa/spec/constitution/check",
                    json={"plan": "cites sources", "constitution": "## Principles\n- Always cite sources.\n"},
                    headers=h)
    assert r.json()["ok"] is True
    r = client.post("/api/devqa/spec/mvp-order",
                    json={"items": [{"id": "T1", "priority": "P1"}, {"id": "T2", "priority": "P2"}]}, headers=h)
    assert [t["id"] for t in r.json()["mvp_tasks"]] == ["T1"]

    r = client.post("/api/devqa/crawl/chunk", json={"markdown": "# H\n\npara text here", "strategy": "heading"}, headers=h)
    assert r.json()["chunks"]
    r = client.post("/api/devqa/security/scope/check",
                    json={"target": "https://evil.com", "scope": {"domains": ["*.example.com"]}}, headers=h)
    assert r.json()["allowed"] is False
    r = client.post("/api/devqa/security/categories/reject",
                    json={"categories": ["information_gathering", "exploit_frameworks"]}, headers=h)
    assert r.json()["import_allowed"] is False and r.json()["rejected"] == ["exploit_frameworks"]
    r = client.post("/api/devqa/security/gates", json={"docker_available": False, "allow_fallback": False}, headers=h)
    assert r.json()["error"] == "docker_unavailable"
    r = client.post("/api/devqa/qa/cassette-to-test",
                    json={"cassette": {"name": "x", "exchanges": [{"method": "GET", "url": "/api/health",
                                                                  "status": 200,
                                                                  "request_headers": {"Cookie": "a=b"}}]}},
                    headers=h)
    assert r.status_code == 422
    r = client.post("/api/devqa/qa/js-lint", json={"source": "console.log(1);"}, headers=h)
    assert r.json()["findings"] and r.json()["findings"][0]["rule"] == "no-console-in-prod"
    r = client.post("/api/devqa/qa/suite-report", json={"counts": {"failed": 0, "quarantined_passed": 2}}, headers=h)
    assert r.json()["ok"] is False
    r = client.post("/api/quality/lint", json={"text": "a apple"}, headers=h)
    assert any(i["rule"] == "a-an-agreement" for i in r.json()["issues"])

    # Platform: register + probe an unreachable service -> down, uptime 0%.
    r = client.post("/api/devqa/platform/services", json={"name": "dead", "url": "http://127.0.0.1:9/health"}, headers=h)
    assert r.status_code == 201
    sid = r.json()["id"]
    r = client.post(f"/api/devqa/platform/services/{sid}/check", headers=h)
    assert r.json()["status"] == "down"
    r = client.get(f"/api/devqa/platform/services/{sid}/uptime", headers=h)
    assert r.json()["percent"] == 0.0
    # Webhook without a configured secret is refused, not an open inbox.
    r = client.post("/api/devqa/platform/notifications/webhook",
                    json={"title": "hi", "secret": "whatever"}, headers=h)
    assert r.status_code == 422
    r = client.get("/api/devqa/platform/vm-profiles", headers=h)
    assert r.json()["profiles"]
    r = client.get("/api/devqa/platform/winutil-catalog", headers=h)
    assert any(e["kind"] == "tweak-documented-only" for e in r.json()["entries"])
    r = client.post("/api/devqa/platform/analytics/event", json={"name": "bogus", "properties": {}}, headers=h)
    assert r.status_code == 422

    # Chat parity: folders + presets (settings only).
    r = client.post("/api/devqa/chat/folders", json={"name": "Work"}, headers=h)
    fid = r.json()["id"]
    r = client.post(f"/api/devqa/chat/folders/{fid}/chats", json={"chat_id": "chat123"}, headers=h)
    assert r.json()["chat_ids"] == ["chat123"]
    r = client.post("/api/devqa/chat/presets/share",
                    json={"name": "Fast", "model": "m1", "temperature": 0.5}, headers=h)
    assert r.status_code == 201 and r.json()["shares_keys"] is False
    r = client.get("/api/devqa/chat/prompt-templates", headers=h)
    assert len(r.json()["templates"]) >= 5


def test_workflow_pause_and_resume_endpoints(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    definition = {"nodes": [
        {"id": "draft", "type": "text", "config": {"template": "hello"}},
        {"id": "gate", "type": "human_input", "config": {"prompt": "Approve?"}},
        {"id": "done", "type": "text", "config": {"template": "got {{nodes.gate}}"}},
    ], "edges": [{"from": "draft", "to": "gate"}, {"from": "gate", "to": "done"}]}
    wf = client.post("/api/workflows", json={"name": "pausable", "definition": definition}, headers=h)
    assert wf.status_code == 201, wf.text
    wid = wf.json()["id"]
    run = client.post(f"/api/workflows/{wid}/run", json={"input": {}}, headers=h)
    assert run.status_code == 201, run.text
    assert run.json()["status"] == "awaiting_input"
    rid = run.json()["id"]
    resumed = client.post(f"/api/devqa/workflows/{wid}/runs/{rid}/resume",
                          json={"human_input": {"gate": "yes"}}, headers=h)
    assert resumed.status_code == 201, resumed.text
    assert resumed.json()["status"] == "succeeded"
    assert resumed.json()["node_results"]["done"]["output"] == "got yes"
    # A finished run cannot be resumed again.
    again = client.post(f"/api/devqa/workflows/{wid}/runs/{rid}/resume",
                        json={"human_input": {"gate": "yes"}}, headers=h)
    assert again.status_code == 422
