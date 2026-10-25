"""A1 (perfect-flow IA & Shell) tests.

Covers, without a browser (the coordinator runs Playwright at merge):
- the pure URL router (shell/router.js) via Node: 8 destinations in
  order, every route shape, legacy redirects, 404, breadcrumb depth.
- the pure palette index (shell/palette_index.js) via Node: every
  required surface is reachable and search filters correctly.
- static shell facts: tabs-on-top bar present and no sidebar / title
  bar left in index.html, settings schema covers every manifest key
  from A2/A3/A4/A5/A6 plus the A1 token keys, all 17 §7 sections exist,
  and destinations.js mounts the five previously-unmounted modules.
- TestClient (port-free): the API surfaces the shell mounts actually
  exist — unauthenticated calls must be refused (401/403), never 404.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

os.environ["TEST_MODE"] = "1"

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

FRONTEND = _ROOT / "mainfiles" / "frontend"
SHELL = FRONTEND / "js" / "features" / "shell"


def _run_node(script: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"node failed:\n{proc.stdout}\n{proc.stderr}"


ROUTER_SCRIPT = """
import assert from 'node:assert';
import { DESTINATIONS, DESTINATION_IDS, parseRoute, urlFor,
  resolveLegacyId, breadcrumbText } from '%s';
assert.deepEqual(DESTINATION_IDS,
  ['chat', 'projects', 'studio', 'code', 'research', 'agents', 'library', 'settings']);
assert.equal(DESTINATIONS.length, 8);
const cases = [
  ['/chat', 'chat', null, null, 1],
  ['/projects', 'projects', null, null, 1],
  ['/projects/abc', 'projects', 'abc', null, 2],
  ['/studio', 'studio', null, null, 1],
  ['/studio/art-1', 'studio', 'art-1', null, 2],
  ['/code', 'code', null, null, 1],
  ['/code/myrepo', 'code', 'myrepo', null, 2],
  ['/research', 'research', null, null, 1],
  ['/research/nb-9', 'research', 'nb-9', null, 2],
  ['/agents', 'agents', null, null, 1],
  ['/agents/task-42', 'agents', 'task-42', null, 2],
  ['/library', 'library', null, null, 1],
  ['/settings', 'settings', null, null, 1],
  ['/settings/models', 'settings', null, 'models', 2],
  ['/agents?section=tasks', 'agents', null, 'tasks', 1],
];
for (const [url, dest, param, section, depth] of cases) {
  const p = parseRoute(url);
  assert.equal(p.dest, dest, url);
  assert.equal(p.param, param, url);
  assert.equal(p.section, section, url);
  assert.equal(p.depth, depth, url);
  assert.equal(urlFor(dest, { param, section }), url, 'round-trip ' + url);
}
// Breadcrumb: only at depth > 1.
assert.equal(breadcrumbText(parseRoute('/agents')), null);
assert.equal(breadcrumbText(parseRoute('/agents/task-42')), 'Agents / task-42');
assert.equal(breadcrumbText(parseRoute('/settings/models')), 'Settings / models');
// Root + legacy paths redirect, never 404.
assert.equal(parseRoute('/').redirect, '/chat');
assert.equal(parseRoute('/home').redirect, '/chat');
assert.equal(parseRoute('/work').redirect, '/agents');
assert.equal(parseRoute('/create').redirect, '/studio');
assert.equal(parseRoute('/knowledge').redirect, '/research');
// Old destination ids redirect, never 404.
assert.equal(resolveLegacyId('home'), '/chat');
assert.equal(resolveLegacyId('work'), '/agents');
assert.equal(resolveLegacyId('create'), '/studio');
assert.equal(resolveLegacyId('knowledge'), '/research');
assert.equal(resolveLegacyId('runs'), '/agents?section=run-history');
assert.equal(resolveLegacyId('skills'), '/library?section=skills');
assert.equal(resolveLegacyId('nope'), null);
// Unknown routes are 404 (the shell renders the 404 page for these).
assert.equal(parseRoute('/definitely-not-a-page').notFound, true);
assert.equal(parseRoute('/chat/extra/deep').notFound, true);
console.log('router ok');
""" % (SHELL / "router.js").as_uri()

PALETTE_SCRIPT = """
import assert from 'node:assert';
import { buildPaletteIndex, searchPaletteIndex, paletteCoverage } from '%s';
const index = buildPaletteIndex({
  destinations: [
    { id: 'chat', title: 'Chat' }, { id: 'projects', title: 'Projects' },
    { id: 'studio', title: 'Studio' }, { id: 'code', title: 'Code' },
    { id: 'research', title: 'Research' }, { id: 'agents', title: 'Agents' },
    { id: 'library', title: 'Library' }, { id: 'settings', title: 'Settings' },
  ],
  settingsSections: [{ id: 'models', label: 'Models & Providers' }, { id: 'data', label: 'Data & Privacy' }],
  skills: [{ name: 'grill' }, { name: 'spec-kit' }],
  prompts: [{ name: 'Code review', body: 'Review this code: ' }],
  models: [{ id: 'gpt-4o' }, { id: 'llama3.1' }],
  chats: [{ id: 'c1', title: 'RAG pipeline notes' }],
});
const cov = paletteCoverage(index);
for (const [k, v] of Object.entries(cov)) assert.equal(v, true, 'coverage ' + k);
assert.ok(searchPaletteIndex(index, 'Projects').some((i) => i.action.dest === 'projects'));
assert.ok(searchPaletteIndex(index, 'Models & Providers').some((i) => i.action.type === 'settings'));
assert.ok(searchPaletteIndex(index, 'grill').some((i) => i.group === 'Skills'));
assert.ok(searchPaletteIndex(index, 'Code review').some((i) => i.action.type === 'run-prompt'));
assert.ok(searchPaletteIndex(index, 'RAG pipeline').some((i) => i.action.type === 'open-chat'));
assert.ok(searchPaletteIndex(index, 'gpt-4o').some((i) => i.action.type === 'switch-model'));
assert.ok(searchPaletteIndex(index, 'zzzz-no-match').length === 0);
assert.equal(searchPaletteIndex(index, '').length, index.length);
console.log('palette ok');
""" % (SHELL / "palette_index.js").as_uri()


def test_router_via_node():
    _run_node(ROUTER_SCRIPT)


def test_palette_index_via_node():
    _run_node(PALETTE_SCRIPT)


def test_shell_html_has_tabs_on_top_no_sidebar():
    # Tabs-on-top correction (2026-10-25): the A1 sidebar rail is gone
    # and the tab bar is the navigation. The old "no tab strip" test
    # asserted the reversed shell (railNav, paletteHintBtn button,
    # helpBtn all lived in the removed sidebar); those are now gone
    # and the tab bar elements are present instead. The composer Runs
    # button stays removed (separate complaint fix).
    html = (FRONTEND / "index.html").read_text()
    for gone in ["id=\"tabStrip\"", "id=\"mainTab\"", "id=\"tabAdd\"",
                 "id=\"toolViewTitle\"", "id=\"toolViewClose\"", "id=\"runsBtn\"",
                 "id=\"sidebar\"", "id=\"railNav\"", "id=\"paletteHintBtn\"",
                 "id=\"helpBtn\"", "id=\"mobileSidebarToggle\"",
                 "id=\"sidebarScrim\""]:
        assert gone not in html, f"removed element still present: {gone}"
    for present in ["id=\"destBreadcrumb\"", "id=\"tabBar\"",
                    "id=\"tabBarScroll\"", "id=\"usageMeter\"",
                    "id=\"profileSection\"", "id=\"newChatBtn\"",
                    "tabbar-kbd-hint"]:
        assert present in html, f"missing shell element: {present}"


def test_settings_schema_covers_every_manifest_key():
    schema = (FRONTEND / "js" / "shared" / "settings_schema.js").read_text()
    keys = set(re.findall(r"\{\s*key:\s*'([^']+)'", schema))
    # A2 composer keys
    assert {"composerMode", "toolMode", "adaptiveDepth"} <= keys
    # A3 project/memory keys
    assert {"memoryRetentionDays", "projectMemoryScope", "projectContextTopK"} <= keys
    # A4 agent-runtime keys
    assert {
        "agentRuntime.defaultApprovalPolicy", "agentRuntime.tokenBudget",
        "agentRuntime.costBudgetUsd", "agentRuntime.maxConcurrentTasks",
        "agentRuntime.circuitErrorThreshold", "agentRuntime.circuitVelocityPerMin",
        "agentRuntime.circuitNoProgressSteps", "agentRuntime.notifyOnTaskDone",
        "agentRuntime.schedulerEnabled",
    } <= keys
    # A5 spec/QA/deploy keys
    assert {
        "spec_tdd_required", "spec_greencontract_min_level", "qa_replay_strict",
        "code_graph_max_files", "deploy_coolify_enabled", "deploy_coolify_url",
        "deploy_quickemu_enabled", "deploy_require_approval", "deploy_sandbox_mode",
    } <= keys
    # A6 studio/provider/marketplace keys
    assert {
        "studio.diagrams.default_accent", "studio.diagrams.default_font",
        "providers.preflight_warnings", "providers.cost_ranked_routing",
        "marketplace.registry_status", "studio.classroom.mp4_export",
    } <= keys
    # A1 design-token keys
    assert {"accentColor", "fontFamily", "cornerRadius", "motionIntensity", "codeTheme"} <= keys
    # Every key's category must be one of the 17 §7 sections.
    cats_block = schema.split("SETTING_CATEGORIES = [", 1)[1].split("];", 1)[0]
    categories = set(re.findall(r"id:\s*'([^']+)'", cats_block))
    assert categories == {
        "general", "appearance", "chat", "models", "tools", "memory", "projects",
        "agents", "skills", "connectors", "voice", "image", "security", "data",
        "code", "advanced", "about",
    }, categories
    used = set(re.findall(r"category:\s*'([^']+)'", schema))
    assert used <= categories, used - categories
    # Row features the spec requires: default display, restart marker,
    # read-only / unavailable handling.
    page = (FRONTEND / "js" / "features" / "settings" / "settings_page.js").read_text()
    assert "Default: " in page and "Requires restart" in page
    assert "readonly" in page and "unavailable" in page
    assert "No settings in this section yet." in page


def test_destinations_mount_unmounted_modules():
    dest = (FRONTEND / "js" / "features" / "shell" / "destinations.js").read_text()
    for mod in ["../projects/projects.js",
                "../agents/taskboard.js", "../code-agent/spec-qa.js",
                "../studio/a6-studio.js"]:
        assert mod in dest, f"destinations.js does not mount {mod}"
    # Settings mounts the memory dashboard (privacy.js import lives in
    # settings_page.js, where the dashboard section renders).
    page = (FRONTEND / "js" / "features" / "settings" / "settings_page.js").read_text()
    assert "../memory/privacy.js" in page
    # View-run re-homing (A2 follow-up #3): Agents -> Run History.
    mv = (FRONTEND / "js" / "features" / "chat" / "message_view.js").read_text()
    assert "showToolSection('agents', 'run-history')" in mv
    assert "showToolSection('work', 'activity')" not in mv


def _api_client(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/a1.db")
    reset_engine_for_testing()
    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def test_shell_mount_targets_exist(tmp_path, monkeypatch):
    """Unauthenticated hits on shell-mounted surfaces: refused, never 404."""
    client = _api_client(tmp_path, monkeypatch)
    for path in ["/api/projects", "/api/agent-tasks", "/api/spec-v2",
                 "/api/studio/catalog", "/api/memory/dashboard",
                 "/api/extensions", "/api/chats", "/api/user/settings",
                 "/api/artifacts", "/api/code-graph/search-v2?q=x"]:
        r = client.get(path)
        assert r.status_code in (401, 403), f"{path} -> {r.status_code}"
