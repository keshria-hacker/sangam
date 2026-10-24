"""Batch 2 (security) tests: guardrails, catalog, isolation, browser
agent, and a live TestClient flow (register -> allowlist -> pending
run -> approve -> findings -> gated report).

No real network in unit tests: recon fetchers are injected fakes.
The browser endpoint test patches the route's driver call with a fake
driver; a real-driver smoke check is reported separately, not run
here (it needs a Chromium launch).
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from backend.security_catalog import CATALOG, EXCLUSIONS, catalog_entry, list_catalog  # noqa: E402
from backend.security_guardrails import (  # noqa: E402
    WORKSPACE_FALLBACK_WARNING,
    check_scope,
    extract_host,
    next_phase,
    run_isolated_command,
    run_passive_recon,
    severity_from_cvss,
)
from backend.browser_agent import (  # noqa: E402
    BrowserActionError,
    run_browser_actions,
    validate_actions,
)


# ------------------------------------------------------------------ scope

def test_check_scope_exact_wildcard_and_deny():
    assert check_scope("https://example.com/app", ["example.com"])
    assert check_scope("app.example.com", ["*.example.com"])
    # Wildcard matches subdomains only, not the apex.
    assert not check_scope("example.com", ["*.example.com"])
    assert not check_scope("https://evil.com/", ["example.com"])
    assert not check_scope("https://example.com.evil.com/", ["example.com"])
    # Empty allowlist denies everything: no proof, no run.
    assert not check_scope("example.com", [])
    assert not check_scope("", ["example.com"])


def test_extract_host_strips_port_and_scheme():
    assert extract_host("https://App.Example.com:8443/x") == "app.example.com"
    assert extract_host("staging.example.com") == "staging.example.com"


def test_severity_bands():
    assert severity_from_cvss(9.8) == "critical"
    assert severity_from_cvss(7.5) == "high"
    assert severity_from_cvss(5.0) == "medium"
    assert severity_from_cvss(2.0) == "low"
    assert severity_from_cvss(0.0) == "none"
    assert severity_from_cvss(None) == "unknown"


def test_phase_order():
    assert next_phase("recon") == "vuln-hunter"
    assert next_phase("validator") == "reporter"
    assert next_phase("reporter") is None


# ---------------------------------------------------------------- catalog

def test_catalog_is_data_only_and_high_risk_disabled():
    assert len(CATALOG) == 10
    names = {e["name"] for e in CATALOG}
    assert names == {"nmap", "nuclei", "ffuf", "subfinder", "httpx", "nikto",
                     "sqlmap", "gobuster", "zaproxy", "amass"}
    for entry in CATALOG:
        assert "curl" not in entry["install"] and "| bash" not in entry["install"]
        assert entry["risk"] in ("low", "medium", "high")
    listed = {e["name"]: e for e in list_catalog()}
    for name in ("nuclei", "ffuf", "sqlmap", "zaproxy"):
        assert listed[name]["enabled"] is False, name
    assert listed["nmap"]["enabled"] is True
    assert catalog_entry("nmap") is not None
    assert catalog_entry("nope") is None
    assert any("DDoS" in e for e in EXCLUSIONS)
    assert any("phishing" in e.lower() for e in EXCLUSIONS)
    assert any("WAF" in e for e in EXCLUSIONS)


# -------------------------------------------------------------- isolation

def test_workspace_fallback_records_warning(tmp_path):
    result = run_isolated_command(["echo", "hello"], tmp_path, docker_present=False)
    assert result.isolation == "workspace-fallback"
    assert result.warning == WORKSPACE_FALLBACK_WARNING
    assert "hello" in result.stdout
    assert result.returncode == 0


def test_docker_path_records_image_even_when_daemon_absent(tmp_path):
    # No docker binary on this machine: the attempt is recorded as the
    # docker backend (image named) rather than silently falling back.
    result = run_isolated_command(["echo", "hi"], tmp_path, docker_present=True)
    assert result.isolation == "docker"
    assert result.image_used == "sangam/security-runner:latest"


# ------------------------------------------------------------ passive recon

def test_passive_recon_uses_injected_fetchers(monkeypatch):
    from backend import security_guardrails as sg
    monkeypatch.setitem(sg.RECON_FETCHERS, "headers", lambda url: {"Server": "x"})
    monkeypatch.setitem(sg.RECON_FETCHERS, "text", lambda url: "body")
    monkeypatch.setitem(sg.RECON_FETCHERS, "dns", lambda host: ["93.184.216.34"])
    out = run_passive_recon("https://example.com")
    assert out["sections"]["headers"]["ok"] is True
    assert out["sections"]["robots.txt"]["data"] == "body"
    assert out["sections"]["dns"]["data"] == ["93.184.216.34"]


# ------------------------------------------------------------ browser agent

def test_browser_validate_rejects_bad_actions():
    with pytest.raises(BrowserActionError):
        validate_actions([])
    with pytest.raises(BrowserActionError):
        validate_actions([{"action": "hack"}])
    with pytest.raises(BrowserActionError):
        validate_actions([{"action": "navigate"}])
    assert validate_actions([{"action": "navigate", "url": "https://example.com"}])


def test_browser_fake_driver_never_touches_real_browser(tmp_path):
    def fake_runner(payload, driver, timeout):
        assert payload["actions"][0]["action"] == "navigate"
        return {"results": [
            {"action": "navigate", "ok": True},
            {"action": "screenshot", "ok": True, "screenshot": "/tmp/shot.png"},
        ]}

    result = run_browser_actions(
        "automation", [{"action": "navigate", "url": "https://example.com"},
                       {"action": "screenshot", "name": "home"}],
        tmp_path, driver_runner=fake_runner)
    assert result.mode == "automation"
    assert result.screenshot_paths == ["/tmp/shot.png"]
    with pytest.raises(BrowserActionError):
        run_browser_actions("merged-mode", [{"action": "navigate", "url": "x"}],
                            tmp_path, driver_runner=fake_runner)


# ------------------------------------------------------------ live API flow

def _api_client(tmp_path, monkeypatch):
    # Importing the routes module registers handlers on the shared
    # router (and the security tables on Base.metadata) BEFORE the app
    # is built — this mirrors the coordinator's api.py wiring.
    import backend.api_routes.security_routes  # noqa: F401
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/sec.db")
    reset_engine_for_testing()

    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth_headers(client):
    creds = {"username": "sec_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


def test_live_flow_allowlist_pending_approve_findings_report(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    with client:
        h = _auth_headers(client)
        # Out-of-scope run is refused BEFORE any tool fires.
        r = client.post("/api/security/runs",
                        json={"target": "https://not-allowed.example/", "tool_class": "recon"}, headers=h)
        assert r.status_code == 403, r.text
        # Allowlist, then a pending run.
        r = client.post("/api/security/allowlist",
                        json={"host_pattern": "*.example.com", "note": "own staging"}, headers=h)
        assert r.status_code == 201, r.text
        allow_id = r.json()["id"]
        r = client.post("/api/security/runs",
                        json={"target": "https://staging.example.com", "scope": "staging only",
                              "tool_class": "recon"}, headers=h)
        assert r.status_code == 201, r.text
        run = r.json()
        assert run["status"] == "pending" and run["phase"] == "recon"
        run_id = run["id"]
        # Approve executes: scope re-checked, isolation recorded.
        r = client.post(f"/api/security/runs/{run_id}/approve", json={}, headers=h)
        assert r.status_code == 200, r.text
        approved = r.json()
        assert approved["status"] == "executed"
        assert approved["isolation"] in ("docker", "workspace-fallback")
        if approved["isolation"] == "workspace-fallback":
            assert approved["isolation_warning"]
        # Finding with CVSS 9.8 -> critical band.
        r = client.post(f"/api/security/runs/{run_id}/findings",
                        json={"title": "SQL injection in search", "cvss_score": 9.8,
                              "owasp_category": "A03:2021-Injection",
                              "evidence": "PoC in audit", "patch_diff": "--- a/x\n+++ b/x"},
                        headers=h)
        assert r.status_code == 201, r.text
        finding = r.json()
        assert finding["severity"] == "critical"
        assert finding["status"] == "candidate"
        # Report gate REFUSES and lists the unvalidated finding.
        r = client.post(f"/api/security/runs/{run_id}/report", json={}, headers=h)
        assert r.status_code == 422, r.text
        assert "SQL injection in search" in r.text
        # Validate PASS, then the report builds.
        r = client.post(f"/api/security/findings/{finding['id']}/validate",
                        json={"verdict": "PASS", "notes": "reproduced on staging"}, headers=h)
        assert r.status_code == 200 and r.json()["validation_verdict"] == "PASS"
        r = client.post(f"/api/security/runs/{run_id}/report", json={}, headers=h)
        assert r.status_code == 200, r.text
        assert "SQL injection in search" in r.json()["report_markdown"]
        # Phase order enforced; audit has the full trail.
        r = client.post(f"/api/security/runs/{run_id}/phase", json={"phase": "reporter"}, headers=h)
        assert r.status_code == 422
        r = client.post(f"/api/security/runs/{run_id}/phase", json={"phase": "vuln-hunter"}, headers=h)
        assert r.status_code == 200 and r.json()["phase"] == "vuln-hunter"
        r = client.get(f"/api/security/runs/{run_id}/audit", headers=h)
        assert r.status_code == 200
        actions = [a["action"] for a in r.json()["audit"]]
        assert "run.created" in actions and "run.approved" in actions
        # Catalog: high-risk nuclei disabled by default; enable works.
        r = client.get("/api/security/catalog", headers=h)
        assert r.status_code == 200
        tools = {t["name"]: t for t in r.json()["tools"]}
        assert tools["nuclei"]["enabled"] is False
        r = client.post("/api/security/catalog/nuclei/enable", json={"enabled": True}, headers=h)
        assert r.status_code == 200 and r.json()["enabled"] is True
        r = client.get("/api/security/catalog", headers=h)
        assert {t["name"]: t for t in r.json()["tools"]}["nuclei"]["enabled"] is True
        # Browser mode without its own approval flag -> 403 (not merged).
        r = client.post(f"/api/security/runs/{run_id}/browser",
                        json={"mode": "automation",
                              "actions": [{"action": "navigate", "url": "https://staging.example.com"}]},
                        headers=h)
        assert r.status_code == 403, r.text
        # Cleanup path: allowlist delete works.
        r = client.delete(f"/api/security/allowlist/{allow_id}", headers=h)
        assert r.status_code == 200, r.text


def test_approval_rechecks_scope_after_allowlist_removed(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    with client:
        h = _auth_headers(client)
        client.post("/api/security/allowlist", json={"host_pattern": "own.example.com"}, headers=h)
        r = client.post("/api/security/runs",
                        json={"target": "https://own.example.com", "tool_class": "recon"}, headers=h)
        run_id = r.json()["id"]
        rows = client.get("/api/security/allowlist", headers=h).json()["targets"]
        client.delete(f"/api/security/allowlist/{rows[0]['id']}", headers=h)
        r = client.post(f"/api/security/runs/{run_id}/approve", json={}, headers=h)
        assert r.status_code == 403, r.text


def test_browser_endpoint_uses_fake_driver(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    with client:
        h = _auth_headers(client)
        client.post("/api/security/allowlist", json={"host_pattern": "*.example.com"}, headers=h)
        r = client.post("/api/security/runs",
                        json={"target": "https://app.example.com", "tool_class": "recon",
                              "browser_security_approved": True}, headers=h)
        run_id = r.json()["id"]
        client.post(f"/api/security/runs/{run_id}/approve", json={}, headers=h)
        import backend.api_routes.security_routes as routes

        def fake_run(mode, actions, profile_dir, **kwargs):
            from backend.browser_agent import BrowserResult
            return BrowserResult(mode=mode, results=[{"action": "navigate", "ok": True}],
                                 screenshot_paths=["/tmp/fake.png"])

        monkeypatch.setattr(routes, "run_browser_actions", fake_run)
        r = client.post(f"/api/security/runs/{run_id}/browser",
                        json={"mode": "security-test",
                              "actions": [{"action": "navigate", "url": "https://app.example.com"}]},
                        headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["screenshot_paths"] == ["/tmp/fake.png"]
        # Every browser action is audited.
        audit = client.get(f"/api/security/runs/{run_id}/audit", headers=h).json()["audit"]
        assert any(a["action"] == "browser.security-test" for a in audit)
