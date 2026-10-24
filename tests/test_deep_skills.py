"""Deep-read Wave 2: SKILLS + PERSONAS.

Covers: invocation semantics + progressive disclosure, stack detection
v2, curated import (preview + per-skill install, never bulk), authoring
contract, skill-creator eval loop, the curated science pack, the
file-based persona registry, and the ponytail ladder / shortcut ledger.
Pytest TestClient/direct tests only — no Playwright, no servers.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mainfiles"))

PACKS = ROOT / "mainfiles" / "backend" / "skills" / "packs"


def _write_skill(directory: Path, frontmatter: str, body: str = "# Body\n") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        f"---\n{frontmatter}---\n\n{body}", encoding="utf-8")
    return directory


# ------------------------------------------------------- 1. invocation + disclosure
def test_model_invocation_flag_blocks_model_and_skill_calls():
    from backend.skills.registry import check_skill_call, is_model_callable
    user_only = {"id": "setup", "name": "Setup", "invocation": "both",
                 "model_invocation": False}
    model_ok = {"id": "tdd", "name": "TDD", "invocation": "both",
                "model_invocation": True}
    assert is_model_callable(user_only) is False
    assert is_model_callable(model_ok) is True
    allowed, reason = check_skill_call("implement", user_only)
    assert allowed is False and "tell the user" in reason
    assert check_skill_call("implement", model_ok)[0] is True
    # disable_model_invocation spelling + invocation=user both block.
    assert is_model_callable({"invocation": "both",
                              "disable_model_invocation": True}) is False
    assert is_model_callable({"invocation": "user"}) is False


def test_progressive_injection_budget_and_single_body():
    from backend.skills.registry import progressive_injection
    body = "BODY-" + "x" * 9000
    fired = [
        {"id": "invoked", "name": "Invoked", "description": "First skill",
         "prompt_template": body, "reference_files": ["references/deep.md"]},
        {"id": "other", "name": "Other", "description": "Second skill",
         "prompt_template": "OTHER-" + "y" * 9000, "reference_files": []},
    ]
    out = progressive_injection(fired, invoked_skill_id="invoked")
    assert "First skill" in out["text"] and "Second skill" in out["text"]
    assert "BODY-" in out["text"]  # invoked skill's body present (capped)
    assert "OTHER-" not in out["text"]  # non-invoked body never injected
    assert "references/deep.md" in out["text"]  # lazy pointer, not content
    assert "deep reference content" not in out["text"]
    assert out["total_chars"] <= out["budget_chars"]
    assert out["invoked_id"] == "invoked"


def test_progressive_injection_never_dumps_whole_bodies():
    from backend.skills.registry import progressive_injection
    fired = [{"id": "a", "name": "A", "description": "d",
              "prompt_template": "Z" * 50000, "reference_files": []}]
    out = progressive_injection(fired)  # auto-fired: first skill is invoked
    assert out["total_chars"] <= out["budget_chars"]
    assert len(out["text"]) < 50000


def test_script_observation_truncates_and_never_includes_source():
    from backend.skills.registry import format_script_observation
    obs = format_script_observation("citation-verify", "verify_citations.py",
                                    "x" * 5000, exit_code=0)
    assert len(obs) < 5000
    assert "verify_citations" in obs  # script name, not its source
    assert "def verify" not in obs


def test_code_agent_call_site_uses_progressive_injection():
    # The old prompt[:2000] dump must be gone from the injection block.
    text = (ROOT / "mainfiles" / "backend" / "code_agent.py").read_text()
    assert "prompt[:2000]" not in text
    assert "progressive_injection" in text
    assert "is_model_callable" in text


# ------------------------------------------------------- 2. stack detection v2
def test_detect_workspace_combos_and_subdirs(tmp_path):
    from backend.skills.recommend import detect_stack, recommend
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["fastapi"]\n', encoding="utf-8")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text(json.dumps({
        "dependencies": {"react": "^18", "typescript": "^5",
                         "tailwindcss": "^3"}}), encoding="utf-8")
    stacks = detect_stack(tmp_path)
    assert "python" in stacks and "fastapi" in stacks
    assert "react" in stacks and "typescript" in stacks
    assert "tailwind" in stacks
    out = recommend(workspace_root=tmp_path, installed_ids=set())
    names = [r["name"] for r in out["recommended"]]
    assert "api-design" in names  # python+fastapi combo
    assert "frontend-design" in names  # frontend bonus
    assert out["frontend_bonus"] is True


def test_detect_rust_go_and_root_only_still_works(tmp_path):
    from backend.skills.recommend import detect_stack, recommend
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\n', encoding="utf-8")
    (tmp_path / "go.mod").write_text("module example.com/x\n", encoding="utf-8")
    stacks = detect_stack(tmp_path)
    assert "rust" in stacks and "go" in stacks
    out = recommend(workspace_root=tmp_path, installed_ids={"tdd"})
    by_name = {r["name"]: r for r in out["recommended"]}
    assert by_name["tdd"]["installed"] is True


def test_detect_ignores_node_modules(tmp_path):
    from backend.skills.recommend import detect_stack
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18"}}), encoding="utf-8")
    assert detect_stack(tmp_path) == []


# ------------------------------------------------------- 3. curated import
def _fake_fetcher_factory(commit="abc123def456", files=None):
    def fetcher(owner, repo, skill, ref):
        return {"commit": commit, "files": dict(files or {
            "SKILL.md": ("---\nid: imported-skill\nname: Imported\n"
                         "category: misc\ninvocation: both\n"
                         "description: imported for tests\n---\n\n# Hi\n").encode(),
        })}
    return fetcher


def test_curated_preview_writes_nothing_and_installs_per_skill(tmp_path, monkeypatch):
    import backend.skills.verify as verify_mod
    monkeypatch.setattr(verify_mod, "USER_SKILLS_ROOT", tmp_path / "skills")
    monkeypatch.setattr(verify_mod, "LOCK_FILE", tmp_path / "skills-lock.json")
    from backend.skills.importer import install_curated, preview_curated_import
    fetcher = _fake_fetcher_factory()
    preview = preview_curated_import("some-owner", "some-repo", "imported-skill",
                                     fetcher=fetcher)
    assert preview["commit"] == "abc123def456"
    assert preview["files"][0]["sha256"]
    assert not (tmp_path / "skills").exists()  # preview writes nothing
    assert preview["checks"]["failed"] == 0
    result = install_curated(preview, fetcher=fetcher)
    assert result["upstream"]["commit"] == "abc123def456"
    lock = json.loads((tmp_path / "skills-lock.json").read_text())
    assert lock["imported-skill"]["upstream"]["commit"] == "abc123def456"


def test_curated_install_refuses_bulk_and_hash_drift(tmp_path, monkeypatch):
    import backend.skills.verify as verify_mod
    monkeypatch.setattr(verify_mod, "USER_SKILLS_ROOT", tmp_path / "skills")
    monkeypatch.setattr(verify_mod, "LOCK_FILE", tmp_path / "skills-lock.json")
    from backend.skills.importer import install_curated, preview_curated_import
    with pytest.raises(ValueError, match="Bulk install"):
        install_curated([{"skill": "x"}])
    preview = preview_curated_import("o", "r", "s", fetcher=_fake_fetcher_factory())
    drifted = _fake_fetcher_factory(files={"SKILL.md": (
        "---\nid: s\nname: S\ncategory: misc\ninvocation: both\n"
        "description: changed\n---\n\n# X\n").encode()})
    with pytest.raises(ValueError, match="changed since preview"):
        install_curated(preview, fetcher=drifted)
    with pytest.raises(ValueError, match="upstream commit"):
        bad = dict(preview, commit="")
        install_curated(bad, fetcher=_fake_fetcher_factory())


# ------------------------------------------------------- 4. authoring contract
def test_authoring_contract_closed_frontmatter_line_cap_banned(tmp_path):
    from backend.skills.verify import run_skill_checks, scan_banned_calls
    d = _write_skill(tmp_path / "bad", "name: Bad\ndescription: d\nsurprise: 1\n",
                     "line\n" * 600)
    (d / "scripts").mkdir()
    (d / "scripts" / "evil.py").write_text("import os\nos.system('ls')\n")
    out = run_skill_checks(d)
    by_check = {c["check"]: c for c in out["checks"]}
    assert by_check["frontmatter-keys"]["status"] == "failed"
    assert by_check["skill-md-lines"]["status"] == "failed"
    assert by_check["banned-calls"]["status"] == "failed"
    assert scan_banned_calls(d)[0]["call"] == "os.system"


def test_scripts_must_have_tests_guard(tmp_path):
    from backend.skills.verify import run_skill_checks
    d = _write_skill(tmp_path / "untested", "name: U\ndescription: d\n")
    (d / "scripts").mkdir()
    (d / "scripts" / "run.py").write_text("print('hi')\n")
    out = run_skill_checks(d)
    by_check = {c["check"]: c for c in out["checks"]}
    assert by_check["scripts-tests"]["status"] == "failed"
    (d / "evals").mkdir()
    (d / "evals" / "case1.json").write_text(json.dumps(
        {"script": "scripts/run.py", "args": [], "expected": "hi"}))
    out = run_skill_checks(d)
    by_check = {c["check"]: c for c in out["checks"]}
    assert by_check["scripts-tests"]["status"] == "passed"


def test_referenced_paths_checked(tmp_path):
    from backend.skills.verify import run_skill_checks
    d = _write_skill(tmp_path / "refs", "name: R\ndescription: d\n",
                     "See references/missing.md for detail.\n")
    out = run_skill_checks(d)
    by_check = {c["check"]: c for c in out["checks"]}
    assert by_check["referenced-paths"]["status"] == "failed"


# ------------------------------------------------------- 5. skill-creator eval loop
def test_creator_loop_rewrites_then_publishes(tmp_path, monkeypatch):
    import backend.skills.verify as verify_mod
    monkeypatch.setattr(verify_mod, "USER_SKILLS_ROOT", tmp_path / "skills")
    monkeypatch.setattr(verify_mod, "LOCK_FILE", tmp_path / "skills-lock.json")
    from backend.skills.creator import draft_skill, evaluate_skill, publish_skill
    skill_dir = tmp_path / "my-skill"
    draft_skill(skill_dir, "My Skill", "Does the thing", "# My Skill\nDo it.\n")
    calls = {"n": 0}

    def runner(prompt, _dir):
        calls["n"] += 1
        return "first attempt misses" if calls["n"] == 1 else "final answer: the thing"
    report = evaluate_skill(
        skill_dir, [{"prompt": "do the thing", "expected_substrings": ["the thing"]}],
        agent_runner=runner,
        rewriter=lambda _r: (skill_dir / "SKILL.md").write_text(
            (skill_dir / "SKILL.md").read_text() + "\nAlways say the thing.\n"),
        max_rounds=3)
    assert report["passed"] is True and report["rounds_run"] == 2
    published = publish_skill(skill_dir, report)
    assert published["name"] == "my-skill"


def test_creator_refuses_publish_without_pass(tmp_path):
    from backend.skills.creator import draft_skill, evaluate_skill, publish_skill
    skill_dir = tmp_path / "nope-skill"
    draft_skill(skill_dir, "Nope", "Does not pass", "# Nope\n")
    report = evaluate_skill(
        skill_dir, [{"prompt": "p", "expected_substrings": ["zzz"]}],
        agent_runner=lambda _p, _d: "nothing relevant")
    assert report["passed"] is False
    with pytest.raises(ValueError, match="Cannot publish"):
        publish_skill(skill_dir, report)
    with pytest.raises(ValueError, match="at least one test prompt"):
        evaluate_skill(skill_dir, [], agent_runner=lambda _p, _d: "x")
    # No runner => no pass can be claimed.
    report = evaluate_skill(skill_dir, [{"prompt": "p", "expected_substrings": []}])
    assert report["passed"] is False


# ------------------------------------------------------- 6. curated science pack
def test_science_review_pack_contract_and_script(tmp_path):
    from backend.skills.verify import run_skill_checks
    pack = PACKS / "science-essentials"
    assert (pack / "pack.yaml").exists()
    skill = pack / "skills" / "citation-verify"
    out = run_skill_checks(skill)
    assert out["failed"] == 0, out
    assert len((skill / "SKILL.md").read_text().splitlines()) <= 500
    draft = tmp_path / "draft.txt"
    draft.write_text("Effect shown [1].\n\n## References\n"
                     "[1] Alpha (2020). Study. doi:10.1000/a\n")
    import subprocess
    r = subprocess.run([sys.executable, str(skill / "scripts" / "verify_citations.py"),
                        "--text", str(draft)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "unresolved=0" in r.stdout
    bad = tmp_path / "bad.txt"
    bad.write_text("Claim [9].\n\n## References\n[1] Uncited. doi:bad\n")
    r = subprocess.run([sys.executable, str(skill / "scripts" / "verify_citations.py"),
                        "--text", str(bad)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "unresolved: citation [9]" in r.stdout


# ------------------------------------------------------- 7. persona registry
def test_persona_roster_valid_and_seeded():
    from backend.persona_registry import assert_roster_valid, load_personas
    personas = assert_roster_valid()
    assert len(personas) >= 12
    assert personas["coder"].division == "engineering"
    assert personas["coder"].method == "implement"
    divisions = {p.division for p in personas.values()}
    assert divisions >= {"engineering", "research", "writing", "product", "design", "data"}


def test_persona_roster_rejects_drift(tmp_path):
    from backend.persona_registry import validate_roster
    root = tmp_path / "personas"
    (root / "engineering").mkdir(parents=True)
    (root / "divisions.json").write_text(json.dumps(
        {"engineering": {"label": "Engineering"}}))
    (root / "engineering" / "dup.md").write_text(
        "---\nname: Dup\ndescription: d\ndivision: research\nrole: x\n"
        "method: implement\n---\n\nBody\n")
    (root / "engineering" / "dup2.md").write_text(
        "---\nname: Dup2\ndescription: d\ndivision: engineering\nrole: y\n"
        "method: implement\n---\n\nBody\n")
    report = validate_roster(root)
    assert any("does not match directory" in e for e in report["errors"])
    assert any("Duplicate method" in e for e in report["errors"])


def test_persona_suggestion_reuses_recommendation_pattern():
    from backend.persona_registry import load_personas, suggest_personas
    personas = load_personas()
    suggested = suggest_personas("please review this diff carefully", personas)
    assert suggested and suggested[0].id == "reviewer"
    assert suggest_personas("the weather is nice today", personas) == []


# ------------------------------------------------------- 8. ponytail ladder + ledger
def test_ladder_modes_and_never_refuse():
    from backend.skills.minimalism import ladder_system_prompt
    lite = ladder_system_prompt("lite")
    assert "Reuse" in lite and "validation, security" in lite
    ultra = ladder_system_prompt("ultra")
    assert "never a refusal" in ultra
    with pytest.raises(ValueError):
        ladder_system_prompt("extreme")


def test_shortcut_ledger_readonly_until_explicit(tmp_path):
    from backend.skills.minimalism import persist_shortcut_ledger, scan_shortcuts
    (tmp_path / "a.py").write_text(
        "# shortcut: regex-parser, switch to real parser at 1000 users\n"
        "# shortcut: quick-hack, no-trigger\n")
    report = scan_shortcuts(tmp_path)
    assert report["count"] == 2 and report["rot_count"] == 1
    assert report["shortcuts"][0]["ceiling"] == "regex-parser"
    with pytest.raises(ValueError, match="explicit"):
        persist_shortcut_ledger(tmp_path, tmp_path / "ledger.md")
    out = persist_shortcut_ledger(tmp_path, tmp_path / "ledger.md", explicit=True)
    assert (tmp_path / "ledger.md").exists() and out["count"] == 2


def test_reviewer_discipline_and_honest_reuse():
    from backend.skills.minimalism import (
        format_review_finding,
        format_review_verdict,
        reuse_pct_for_diff,
    )
    finding = format_review_finding("Must", "safe", "auth check",
                                    "missing check", "add check", "breach")
    verdict = format_review_verdict([finding], lean_notes=["drop helper"],
                                    not_checked=["load"])
    assert verdict.startswith("Verdict: CHANGES REQUIRED")
    assert "Not checked: load" in verdict
    reuse = reuse_pct_for_diff("diff", graph={})
    assert reuse["reuse_pct"] is None and "no per-diff reuse metric" in reuse["reason"]
    with pytest.raises(ValueError):
        format_review_finding("Trivial", "safe", "x", "y", "z", "w")
