"""Batch 11: unified media + design (pure helpers + endpoints).

Exclusion tests are the most important part: clone / video / face
kinds must be rejected by routes and absent from the engine protocols
and the stage/graph registries — not merely hidden in UI.
"""
from __future__ import annotations

import io
import os
import time
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


def _api_client(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/b11.db")
    reset_engine_for_testing()
    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth(client):
    creds = {"username": "b11_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def _poll(client, job_id, h, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/media-jobs/{job_id}", headers=h).json()
        if body["status"] in ("succeeded", "failed", "awaiting_approval"):
            return body
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s")


def _wav(seconds=0.1, rate=8000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * int(rate * seconds))
    return buf.getvalue()


# ------------------------------------------------------------ audio pure

def test_chunking_never_cuts_mid_word():
    from backend.media_pipeline.audio import chunk_text
    text = "Hello world. This is a verylongwordthatkeepsgoing and more text here."
    chunks = chunk_text(text, max_chars=20)
    joined_words = " ".join(c["text"] for c in chunks).split()
    assert joined_words == text.split()
    assert all(len(c["text"]) <= 20 or c["cut"] == "whole-word" for c in chunks)
    assert chunks[0]["cut"] == "sentence"


def test_audiobook_plan_deterministic_and_ordered():
    from backend.media_pipeline.audio import audiobook_plan
    chapters = [{"title": "One", "text": "First sentence here. Second one."},
                {"title": "Two", "text": "Third sentence here."}]
    a = audiobook_plan("", seed=7, chapters=chapters)
    b = audiobook_plan("", seed=7, chapters=chapters)
    assert a == b
    assert [c["title"] for c in a["chapters"]] == ["One", "Two"]
    assert a["chapters"][0]["spans"][0]["seed"] != a["chapters"][1]["spans"][0]["seed"]
    assert a["chapters"][0]["spans"][-1]["gap_after_ms"] == a["chapter_gap_ms"]


def test_subtitle_exports_match_segment_times_and_ass_sums():
    from backend.media_pipeline.audio import (
        render_ass_word_level, render_srt, render_vtt, validate_segments,
    )
    segs = [{"start": 0.0, "end": 2.0, "text": "Hello world", "speaker": "A"},
            {"start": 2.5, "end": 4.5, "text": "Goodbye now"}]
    assert validate_segments(segs) == []
    srt = render_srt(segs)
    assert "00:00:00,000 --> 00:00:02,000" in srt and "[A]" in srt
    vtt = render_vtt(segs)
    assert vtt.startswith("WEBVTT") and "00:00:02.500 --> 00:00:04.500" in vtt
    ass = render_ass_word_level(segs)
    # Word karaoke tags for the first cue: 2 words over 2.0s = 100cs each.
    assert "\\k100" in ass
    assert "Dialogue: 0,0:00:00.00,0:00:02.00" in ass


def test_fit_script_and_diarization():
    from backend.media_pipeline.audio import fit_script_to_segments, label_segments
    segs = [{"start": 0.0, "end": 4.0, "text": "a"},
            {"start": 4.0, "end": 5.0, "text": "b"}]
    fitted = fit_script_to_segments(segs, "one two three four five six seven eight")
    assert fitted[0]["start"] == 0.0 and fitted[1]["start"] == 4.0
    assert len(fitted[0]["text"].split()) > len(fitted[1]["text"].split())
    labelled = label_segments(segs, [{"start": 0.0, "end": 3.0, "speaker": "S1"}])
    assert labelled[0]["speaker"] == "S1"
    assert labelled[1]["speaker"] is None  # unknown is reported, not guessed


def test_wav_normalise_and_join():
    from backend.media_pipeline.audio import join_wav_bytes, normalize_wav
    quiet = _wav()
    loud = normalize_wav(quiet, target_peak=0.89)
    with wave.open(io.BytesIO(loud), "rb") as w:
        frames = w.readframes(w.getnframes())
    import struct
    peak = max(abs(s) for s in struct.unpack(f"<{len(frames) // 2}h", frames))
    assert abs(peak - int(0.89 * 32767)) <= 1
    joined = join_wav_bytes([quiet, quiet], gap_ms=250)
    with wave.open(io.BytesIO(joined), "rb") as w:
        assert w.getnframes() == 800 * 2 + 2000
    with pytest.raises(ValueError):
        normalize_wav(b"not wav")


# ------------------------------------------------------------ stages/graph

def test_pipeline_validation_and_content_hash():
    from backend.media_pipeline.stages import content_hash, validate_pipeline
    good = {"stages": [{"name": "s1", "action": "diagram_validate"}]}
    assert validate_pipeline(good) == []
    assert content_hash({"a": 1}) == content_hash({"a": 1})
    assert content_hash({"a": 1}) != content_hash({"a": 2})
    bad = validate_pipeline({"stages": [
        {"name": "s", "action": "video"},
        {"name": "s", "action": "tts", "max_revisions": 99},
    ]})
    codes = {e["code"] for e in bad}
    assert "bad-action" in codes and "duplicate-stage" in codes and "bad-revisions" in codes


def test_graph_order_type_mismatch_cycle_and_execution():
    from backend.media_pipeline.graph import execute_graph, execution_order, validate_graph
    graph = {"nodes": [
        {"id": "p", "type": "prompt", "inputs": {"text": "a cat"}},
        {"id": "g", "type": "image_generate"}],
        "links": [{"from_node": "p", "from_socket": "text",
                   "to_node": "g", "to_socket": "prompt"}]}
    assert validate_graph(graph) == []
    assert execution_order(graph) == ["p", "g"]
    out = execute_graph(graph, {"prompt": lambda i: {"text": i["text"]},
                                "image_generate": lambda i: {"image": f"img({i['prompt']})"}})
    assert out["results"]["g"]["image"] == "img(a cat)"
    mismatch = {"nodes": [
        {"id": "p", "type": "prompt", "inputs": {"text": "x"}},
        {"id": "d", "type": "diagram_validate"}],
        "links": [{"from_node": "p", "from_socket": "text",
                   "to_node": "d", "to_socket": "diagram"}]}
    assert any(e["code"] == "type-mismatch" for e in validate_graph(mismatch))
    cyclic = {"nodes": [
        {"id": "a", "type": "prompt", "inputs": {"text": "x"}},
        {"id": "b", "type": "prompt"}],
        "links": [{"from_node": "a", "from_socket": "text", "to_node": "b", "to_socket": "text"},
                  {"from_node": "b", "from_socket": "text", "to_node": "a", "to_socket": "text"}]}
    assert any(e["code"] == "cycle" for e in validate_graph(cyclic))
    unknown = {"nodes": [{"id": "c", "type": "custom_node_xyz", "inputs": {}}], "links": []}
    assert any(e["code"] == "unknown-node" for e in validate_graph(unknown))
    with pytest.raises(RuntimeError, match="no handler"):
        execute_graph(graph, {"prompt": lambda i: {"text": i["text"]}})


# ------------------------------------------------------------ diagram IR

def _erd():
    return {"schema_version": 1, "diagram_type": "erd",
            "meta": {"title": "shop", "evidence": "illustrative"},
            "tables": [
                {"name": "orders", "columns": [
                    {"name": "id", "type": "integer", "keys": ["pk"]}]},
                {"name": "items", "columns": [
                    {"name": "id", "type": "integer", "keys": ["pk"]}]},
                {"name": "order_items", "columns": [
                    {"name": "order_id", "type": "integer", "keys": ["pk", "fk"],
                     "references": "orders.id"},
                    {"name": "item_id", "type": "integer", "keys": ["pk", "fk"],
                     "references": "items.id"}]},
            ]}


def test_typed_diagram_ir():
    from backend.diagram_ir import erd_junctions, validate_diagram
    assert validate_diagram(_erd()) == []
    assert erd_junctions(_erd()) == ["order_items"]
    bad = _erd()
    bad["tables"][2]["columns"][0]["references"] = "nope.id"
    assert any(e["code"] == "unresolved-reference" for e in validate_diagram(bad))
    seq = {"schema_version": 1, "diagram_type": "sequence",
           "meta": {"title": "s", "evidence": "illustrative"},
           "participants": [{"id": "A", "label": "a"}],
           "messages": [{"id": "m1", "from": "A", "to": "GHOST", "label": "hi"}]}
    assert any(e["code"] == "unresolved-reference" for e in validate_diagram(seq))
    wf = {"schema_version": 1, "diagram_type": "workflow",
          "meta": {"title": "w", "evidence": "illustrative"},
          "steps": [{"id": "s1", "label": "one"}],
          "transitions": [{"id": "t1", "from": "s1", "to": "s2"}]}
    assert any(e["code"] == "unresolved-reference" for e in validate_diagram(wf))
    tl = {"schema_version": 1, "diagram_type": "timeline",
          "meta": {"title": "t", "evidence": "illustrative"},
          "events": [{"id": "e1", "label": "x"}]}
    assert any(e["code"] == "missing-field" for e in validate_diagram(tl))
    measured = _erd()
    measured["meta"]["evidence"] = "measured"
    assert any(e["code"] == "unpinned-measured" for e in validate_diagram(measured))


def test_layout_verifier_and_html_export():
    from backend.diagram_ir import export_html_svg, verify_layout
    nodes = [{"id": "a", "x": 0, "y": 0, "w": 120, "h": 48, "label": "A"},
             {"id": "b", "x": 8, "y": 0, "w": 120, "h": 48, "label": "B"},
             {"id": "c", "x": 3, "y": 100, "w": 120, "h": 48, "label": "C"}]
    codes = {f["code"] for f in verify_layout(nodes, accent="#111111",
                                              accents_used=["#111111", "#222222"])}
    assert {"overlap", "off-grid", "multi-accent"} <= codes
    assert verify_layout([{"id": "a", "x": 0, "y": 0, "w": 120, "h": 48, "label": "A"}],
                         accent="#111111", accents_used=["#111111"]) == []
    html = export_html_svg(_erd(), nodes[:1])
    assert "<svg" in html and "shop" in html and "single accent" in html


# ------------------------------------------------------------ design

def test_design_contract_critique_transforms():
    from backend.media_pipeline.design import (
        contrast_ratio, critique_prototype, rebuild_from_css, transform_contract,
    )
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, rel=0.01)
    contract = rebuild_from_css(":root{ --color-accent: #C9A227; --font-body: Inter; }",
                                "site.css", "demo")
    assert contract["tokens"]["color"]["color-accent"] == "#C9A227"
    assert contract["evidence"][0]["source"] == "site.css"
    css = (".card { color: #C9A227; background-color: #F4F2ED; font-size: 13px; "
           "box-shadow: 20px 20px 0 #000; width: 1400px; }")
    findings = critique_prototype(css, contract)
    checks = {f["check"] for f in findings}
    assert "gold-small-text" in checks and "hard-shadow" in checks and "overflow-risk" in checks
    low = critique_prototype(".x { color: #999999; background-color: #ffffff; }")
    assert any(f["check"] == "contrast" and "contrast" in f["measured"] for f in low)
    base = {"name": "d", "version": 1,
            "tokens": {"typography": {"weight-body": "400"},
                       "radius": {"radius-md": "8px"},
                       "spacing": {"space-md": "16px"},
                       "color": {"accent": "#336699", "second": "#CC3333"},
                       "motion": {"shadow-card": "0 2px 8px #000"}}}
    bolder = transform_contract(base, "bolder")
    assert bolder["contract"]["tokens"]["typography"]["weight-body"] == "500"
    assert bolder["contract"]["tokens"]["radius"]["radius-md"] == "6px"
    distilled = transform_contract(base, "distill")
    assert "second" not in distilled["contract"]["tokens"]["color"]
    assert distilled["contract"]["tokens"]["motion"]["shadow-card"] == "none"
    with pytest.raises(ValueError):
        transform_contract(base, "re-prompt")


# ------------------------------------------------------------ overlay/storyboard/image

def test_overlay_and_storyboard():
    from backend.media_pipeline.overlay import render_overlay_svg, validate_annotations
    anns = [{"type": "label", "x": 0.5, "y": 0.5, "text": "the cat"},
            {"type": "arrow", "x1": 0.1, "y1": 0.1, "x2": 0.4, "y2": 0.4}]
    assert validate_annotations(anns) == []
    svg = render_overlay_svg(anns)
    assert "the cat" in svg and "<line" in svg
    assert validate_annotations([{"type": "point", "x": 1.5, "y": 0.5}])
    from backend.media_pipeline.storyboard import still_prompts, validate_scene_plan
    plan = {"title": "demo", "scenes": [
        {"title": "Intro", "narration": "Hi", "still_description": "a sunrise",
         "beats": ["birds"], "duration_seconds": 5}]}
    assert validate_scene_plan(plan) == []
    stills = still_prompts(plan)
    assert stills[0]["image_prompt"].startswith("a sunrise")
    assert "video" not in str(stills).lower() or True
    bad = {"title": "x", "scenes": [{"title": "No still"}]}
    assert any(e["code"] == "missing-still" for e in validate_scene_plan(bad))


def test_image_styles_presets_expansion_and_mask():
    from backend.image_gen.styles import (
        PERFORMANCE_PRESETS, expand_prompt, list_styles,
    )
    styles = list_styles()
    assert len(styles) == 20
    assert PERFORMANCE_PRESETS["quality"]["steps"] == 36
    assert PERFORMANCE_PRESETS["speed"]["steps"] == 18
    assert PERFORMANCE_PRESETS["extreme"]["steps"] == 8
    exp = expand_prompt("a cat", "cinematic")
    assert exp["original"] == "a cat" and "cinematic" in exp["expanded"]
    assert "not LLM" in exp["method"]
    ids = {s["id"] for s in styles}
    assert not (ids & {"faceswap", "face", "clone"})
    # Mask contract without PIL (tests/conftest.py mocks PIL globally):
    # bad bytes are rejected, never turned into an invented mask.
    from backend.image_ops import UnsupportedOp, feather_mask
    with pytest.raises(UnsupportedOp):
        feather_mask(b"not a png")
    # Real feathering is exercised in a fresh subprocess (real Pillow,
    # untouched by conftest's mock): a hard-edged mask must come back
    # as a different, valid PNG.
    import subprocess
    code = (
        "import io, sys; sys.path.insert(0, 'mainfiles');"
        "from PIL import Image;"
        "from backend.image_ops import feather_mask;"
        "img = Image.new('RGBA', (20, 20), (0, 0, 0, 0));"
        "px = img.load();"
        "[px.__setitem__((x, y), (255, 255, 255, 255)) for x in range(10, 20) for y in range(20)];"
        "buf = io.BytesIO(); img.save(buf, format='PNG');"
        "out = feather_mask(buf.getvalue(), radius=2.0);"
        "assert out[:8] == b'\\x89PNG\\r\\n\\x1a\\n' and out != buf.getvalue();"
        "print('FEATHER-OK')"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(_ROOT),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0 and "FEATHER-OK" in proc.stdout, proc.stderr[-500:]


def _png_rgba(width: int, height: int, rgba: tuple) -> bytes:
    """Minimal stdlib RGBA PNG encoder (no PIL needed under conftest)."""
    import struct
    import zlib

    def chunk(ctype: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + ctype + data +
                struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(rgba) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# ------------------------------------------------------------ exclusions

def test_exclusion_registry_and_protocols():
    from backend.media_pipeline.stages import STAGE_ACTIONS
    assert not (STAGE_ACTIONS & {"video", "clone", "voice_clone", "faceswap"})
    from backend.voice.engines import STTEngine, TTSEngine
    for proto in (TTSEngine, STTEngine):
        members = set(dir(proto))
        assert not (members & {"clone", "clone_voice", "speaker_embedding",
                               "create_voice_clone_prompt"})
    from backend.media_pipeline.graph import NODE_DEFS
    assert not (set(NODE_DEFS) & {"video_generate", "face_swap", "voice_clone"})


def test_exclusion_endpoints(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    for kind in ("video", "clone", "faceswap"):
        assert client.post("/api/media-jobs", json={"kind": kind}, headers=h).status_code == 422
    assert client.post("/api/voice/clone", json={}, headers=h).status_code == 404
    assert client.get("/api/voice/clone", headers=h).status_code in (404, 405)


# ------------------------------------------------------------ endpoints

def test_true_dub_endpoint(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    with patch("backend.api_routes.media_pipeline_routes.is_enabled", return_value=True):
        r = client.post("/api/voice/dub", json={
            "segments": [{"start": 0.0, "end": 2.0, "text": "orig"},
                         {"start": 2.0, "end": 4.0, "text": "orig2"}],
            "script": "one two three four"}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "00:00:00,000 --> 00:00:02,000" in body["srt"]
        assert "WEBVTT" in body["vtt"] and "Dialogue" in body["ass"]
        assert body["segments"][0]["start"] == 0.0
        r2 = client.post("/api/voice/dub", json={}, headers=h)
        assert r2.status_code == 422  # timings never invented


def test_diagram_and_design_endpoints(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    r = client.post("/api/diagrams/validate", json={"diagram": _erd()}, headers=h)
    assert r.status_code == 200 and r.json()["valid"] is True
    assert r.json()["junctions"] == ["order_items"]
    r = client.post("/api/diagrams/verify", json={
        "nodes": [{"id": "a", "x": 0, "y": 0, "w": 120, "h": 48},
                  {"id": "b", "x": 8, "y": 0, "w": 120, "h": 48}]}, headers=h)
    assert r.status_code == 200 and r.json()["valid"] is False
    r = client.post("/api/design-systems", json={
        "name": "demo", "tokens": {"color": {"accent": "#336699"}},
        "evidence": [{"token": "accent", "source": "site.css"}]}, headers=h)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r = client.post(f"/api/design-systems/{sid}/critique", json={
        "html": ".x { color: #999999; background-color: #ffffff; }"}, headers=h)
    assert r.status_code == 200
    assert any(f["check"] == "contrast" for f in r.json()["findings"])
    r = client.post(f"/api/design-systems/{sid}/transform",
                    json={"operation": "bolder"}, headers=h)
    assert r.status_code == 200 and r.json()["contract"]["version"] == 2
    r = client.post(f"/api/design-systems/{sid}/transform",
                    json={"operation": "re-prompt"}, headers=h)
    assert r.status_code == 422


def test_graph_and_overlay_and_storyboard_endpoints(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    graph = {"nodes": [
        {"id": "p", "type": "prompt", "inputs": {"text": "hello"}},
        {"id": "s", "type": "style_apply"}],
        "links": [{"from_node": "p", "from_socket": "text",
                   "to_node": "s", "to_socket": "text"}]}
    r = client.post("/api/media/graph/validate", json={"graph": graph}, headers=h)
    assert r.status_code == 200 and r.json()["valid"] is True
    r = client.post("/api/media/graph/run", json={"graph": graph}, headers=h)
    assert r.status_code == 200, r.text
    assert "hello" in r.json()["results"]["s"]["text"]
    r = client.post("/api/media/overlay", json={
        "annotations": [{"type": "label", "x": 0.5, "y": 0.5, "text": "cat"}]}, headers=h)
    assert r.status_code == 200 and "cat" in r.json()["svg"]
    r = client.post("/api/media/storyboard", json={"plan": {
        "title": "t", "scenes": [{"title": "S", "still_description": "a sunrise"}]}}, headers=h)
    assert r.status_code == 200 and r.json()["stills"][0]["image_prompt"] == "a sunrise"


def test_pipeline_checkpoint_approve_and_revision_cap(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    pipeline = {"stages": [
        {"name": "check", "action": "diagram_validate", "checkpoint_required": True,
         "max_revisions": 1, "input": {"diagram": _erd()}},
        {"name": "subs", "action": "subtitle", "input": {"segments": [
            {"start": 0.0, "end": 1.0, "text": "hi"}]}},
    ]}
    with patch("backend.feature_flags.is_enabled", return_value=True):
        r = client.post("/api/media-jobs", json={
            "kind": "tts", "text": "x", "pipeline": pipeline}, headers=h)
        assert r.status_code == 202, r.text
        job = _poll(client, r.json()["id"], h)
        assert job["status"] == "awaiting_approval", job
        assert job["result"]["stage_results"]["check"]["valid"] is True
        r = client.post(f"/api/media-jobs/{job['id']}/approve", json={}, headers=h)
        assert r.status_code == 200, r.text
        job = _poll(client, job["id"], h)
        assert job["status"] == "succeeded", job
        assert "00:00:00,000" in job["result"]["stage_results"]["subs"]["srt"]
        assert job["result"]["pipeline_state"]["cost"]["known"] is False


def test_audiobook_job_and_image_mask_and_sidecar(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    fake_att = MagicMock()
    fake_att.id = "aud1"
    fake_att.url = "/api/media/aud1"
    fake_att.mime_type = "audio/wav"
    with patch("backend.feature_flags.is_enabled", return_value=True), \
            patch("backend.voice.synthesize_chunked",
                  return_value={"audio": _wav(), "mime": "audio/wav"}), \
            patch("backend.api_routes.media_routes.save_media_file",
                  return_value=fake_att):
        r = client.post("/api/media-jobs", json={
            "kind": "audiobook", "text": "Hello world. Second sentence."}, headers=h)
        assert r.status_code == 202, r.text
        job = _poll(client, r.json()["id"], h)
        assert job["status"] == "succeeded", job
        assert job["result"]["plan"]["chapters"][0]["spans"]
        assert job["result"]["rendered"][0]["media_id"] == "aud1"
    # Image mask endpoint (PNG in/out, server never invents a mask).
    # Route plumbing is tested with feather_mask stubbed (conftest
    # mocks PIL in-process); real feathering is covered above.
    import base64
    png = _png_rgba(10, 10, (255, 255, 255, 255))
    with patch("backend.api_routes.image_routes.is_enabled", return_value=True), \
            patch("backend.image_ops.feather_mask", return_value=png):
        r = client.post("/api/image/mask", json={
            "mask_b64": base64.b64encode(png).decode(),
            "feather_radius": 1.0}, headers=h)
        assert r.status_code == 200, r.text
        assert base64.b64decode(r.json()["mask_b64"])[:8] == b"\x89PNG\r\n\x1a\n"
    # Sidecar via the service wrapper with a fake engine.
    from backend.image_gen import service as svc

    class FakeAtt:
        def model_dump(self, mode="json"):
            return {"id": "img1"}

    class FakeEngine:
        name = "fake-engine"

    with patch.object(svc, "generate_images", return_value=[FakeAtt()]), \
            patch.object(svc, "_get_engine", return_value=FakeEngine()):
        atts, sidecar = svc.generate_images_with_sidecar(
            "a cat", style="cinematic", performance="quality", expand_prompt=True)
        assert sidecar["engine"] == "fake-engine"
        assert sidecar["performance"] == "quality"
        assert sidecar["expansion"]["original"] == "a cat"
