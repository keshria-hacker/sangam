"""Batch 7 (Writing Quality + Diagrams + Image Ops) tests.

Covers: slop detect returns detections + unchanged text, edit returns
minimum edits + what-changed; lint flags repeated word + confusion +
double space and never rewrites; ADHD list cap (7 -> 5 + "+2 more")
and the settings schema no longer claims answer-first/numbered-steps;
diagram lint flags 2 accent colors; draw.io XML and Excalidraw JSON
imports carry the sample labels + an edge; brand apply substitutes the
accent; image ops with a fake engine (vary returns an artifact,
unsupported op returns 422 not a fake image, upscale falls back to a
labelled Pillow resize, describe with no vision model returns 503).
"""
from __future__ import annotations

import asyncio
import base64
import io
import os
import sys
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import backend.api_routes.image_routes as image_routes  # noqa: E402
import backend.image_ops as image_ops  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.database import Base, get_engine, reset_engine_for_testing  # noqa: E402
from backend.image_gen.engines import GeneratedImage  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.ratelimit_redis import reset_rate_limit_store_for_testing  # noqa: E402
from backend.response_quality.adhd import adhd_format, adhd_style_text  # noqa: E402
from backend.response_quality.slop import detect_slop, remove_slop_with_changes  # noqa: E402
from backend.writing_lint import lint_text  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _api_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/b7w.db")
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    reset_engine_for_testing()
    reset_rate_limit_store_for_testing()

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


@pytest.fixture
def client(tmp_path, monkeypatch):
    return _api_client(tmp_path, monkeypatch)


def _auth_headers(client):
    creds = {"username": "b7w_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


# ------------------------------------------------------------------ slop

SLOP_PASSAGE = (
    "Delve into the rich tapestry of this crucial landscape. "
    "Furthermore, it is vital to note the vibrant, bustling scene."
)


def test_slop_detect_names_patterns_without_rewriting():
    dets = detect_slop(SLOP_PASSAGE)
    names = {d["pattern"] for d in dets}
    assert len(names) >= 3
    assert {"delve-into", "crucial", "furthermore"} <= names
    assert all(d["line"] == 1 and d["quote"] for d in dets)


def test_slop_edit_returns_what_changed():
    cleaned, changes = remove_slop_with_changes(SLOP_PASSAGE)
    assert "delve" not in cleaned.lower() and "tapestry" not in cleaned.lower()
    assert changes
    assert all({"pattern", "before", "after"} <= set(c) for c in changes)
    assert any(c["pattern"] == "delve-into" and c["after"] == "Look at" for c in changes)


def test_preview_detect_leaves_text_unchanged_and_edit_shows_changes(client):
    h = _auth_headers(client)
    r = client.post("/api/quality/preview", json={"text": SLOP_PASSAGE, "mode": "detect"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cleaned"] == SLOP_PASSAGE
    assert body["diff"] == ""
    assert len(body["detections"]) >= 3
    r = client.post("/api/quality/preview", json={"text": SLOP_PASSAGE}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cleaned"] != SLOP_PASSAGE
    assert body["what_changed"]
    # Backward compatibility: original/cleaned/diff/stats all still present.
    assert {"original", "cleaned", "diff", "stats"} <= set(body)


# ------------------------------------------------------------------ lint

def test_lint_flags_repetition_confusion_double_space_and_never_rewrites():
    text = "This is the the test.  Their going to the store. Hello.World recieve"
    issues = lint_text(text)
    rules = {i["rule"] for i in issues}
    assert "repeated-word" in rules
    assert "confusion-candidate" in rules
    assert "double-space" in rules
    assert "unknown-word" in rules
    assert all("cleaned" not in i for i in issues)
    r_rules = {i["rule"] for i in lint_text("The cat sat on the mat.")}
    assert "repeated-word" not in r_rules and "confusion-candidate" not in r_rules


def test_lint_api(client):
    h = _auth_headers(client)
    r = client.post("/api/quality/lint",
                    json={"text": "This is the the test."}, headers=h)
    assert r.status_code == 200, r.text
    assert any(i["rule"] == "repeated-word" for i in r.json()["issues"])


# ------------------------------------------------------------------ adhd

def test_adhd_list_cap_7_to_5_plus_note():
    text = "\n".join(f"- item {i}" for i in range(7))
    out, n = adhd_format(text)
    assert out.count("- item") == 5
    assert "+2 more" in out
    assert n >= 1


def test_adhd_schema_no_longer_claims_answer_first_or_numbered_steps():
    schema = (_ROOT / "mainfiles/frontend/js/shared/settings_schema.js").read_text()
    line = next(l for l in schema.splitlines() if "adhdFriendly" in l)
    assert "Answer-first" not in line
    assert "numbered steps" not in line
    assert "caps lists at 5" in line


def test_adhd_style_endpoint_is_honest_about_wiring(client):
    h = _auth_headers(client)
    r = client.get("/api/quality/adhd-style", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    # Wave-2 merge fix: Wave 1 wired ADHD into chat by design, so the
    # old wired_into_chat=false assertion is stale. The style block is
    # injected into the chat system prompt when the user's adhdFriendly
    # setting is on, and only then.
    assert body["wired_into_chat"] is True
    assert body["wired_behind_setting"] == "adhdFriendly"
    assert "Cap lists at 5" in body["style"]
    assert "Lead with the next action" in body["style"]
    assert adhd_style_text() == body["style"]


# -------------------------------------------------------------- diagrams

def test_diagram_lint_flags_two_accent_colors(client):
    h = _auth_headers(client)
    src = "flowchart TD\n    A[Start] --> B[End]\n    style A fill:#ff0000\n    style B fill:#00ff00"
    r = client.post("/api/diagrams/lint", json={"mermaid": src}, headers=h)
    assert r.status_code == 200, r.text
    assert any(i["rule"] == "multiple-accent-colors" for i in r.json()["issues"])


def test_diagram_catalogue_has_12_plus_types(client):
    h = _auth_headers(client)
    r = client.get("/api/diagrams/catalogue", headers=h)
    assert r.status_code == 200
    ids = {d["id"] for d in r.json()["diagrams"]}
    assert len(ids) >= 12
    assert {"flowchart", "sequence", "class", "er", "state", "gantt", "pie",
            "journey", "mindmap", "git-graph", "quadrant", "timeline"} <= ids
    assert all(d.get("template") and d.get("use") for d in r.json()["diagrams"])


DRAWIO_SAMPLE = """<mxfile><diagram><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="2" value="Start here" vertex="1" parent="1"/>
<mxCell id="3" value="Finish line" vertex="1" parent="1"/>
<mxCell id="4" value="" edge="1" source="2" target="3" parent="1"/>
</root></mxGraphModel></diagram></mxfile>"""


def test_drawio_import_carries_labels_and_edge(client):
    h = _auth_headers(client)
    r = client.post("/api/diagrams/import",
                    json={"format": "drawio", "content": DRAWIO_SAMPLE}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Start here" in body["mermaid"] and "Finish line" in body["mermaid"]
    assert "N1 --> N2" in body["mermaid"]
    assert body["warnings"]  # best-effort disclaimer present


def test_excalidraw_import_carries_shapes_and_edge(client):
    import json

    h = _auth_headers(client)
    sample = json.dumps({"elements": [
        {"id": "a", "type": "rectangle", "name": "Alpha box"},
        {"id": "b", "type": "diamond", "name": "Choice point"},
        {"id": "c", "type": "arrow",
         "startBinding": {"elementId": "a"}, "endBinding": {"elementId": "b"}},
        {"id": "d", "type": "freedraw"},
    ]})
    r = client.post("/api/diagrams/import",
                    json={"format": "excalidraw", "content": sample}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Alpha box" in body["mermaid"] and "Choice point" in body["mermaid"]
    assert "N1 --> N2" in body["mermaid"]
    assert any("freedraw" in w for w in body["warnings"])


def test_brand_apply_substitutes_accent(client):
    h = _auth_headers(client)
    r = client.post("/api/diagrams/brands",
                    json={"name": "Acme", "accent": "#123456"}, headers=h)
    assert r.status_code == 200, r.text
    brand_id = r.json()["id"]
    r = client.post("/api/diagrams/brands/apply",
                    json={"template": "flowchart TD\n    A[Hi] %% __ACCENT__",
                          "brand_id": brand_id}, headers=h)
    assert r.status_code == 200, r.text
    assert "#123456" in r.json()["mermaid"]
    assert "__ACCENT__" not in r.json()["mermaid"]


# ------------------------------------------------------------- image ops

class _FakeEngine:
    name = "fake"

    def variations(self, image_bytes):
        return [GeneratedImage(b"fake-varied", "image/png")]

    def edits(self, image_bytes, prompt, mask_bytes=None):
        return [GeneratedImage(b"fake-edited", "image/png")]


class _BareEngine:
    name = "bare"


# 8x8 red PNG, embedded: tests/conftest.py replaces PIL with an empty
# mock, so test inputs must not depend on real PIL at import time.
_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEklEQVR4nGP8z4AdMOEQH6QSAM1BAQ/oQeJvAAAAAElFTkSuQmCC"
)


def _png_bytes():
    return _PNG_B64


@pytest.fixture
def real_pil():
    """Temporarily restore the real PIL the root conftest mocked away.

    Only for the Pillow-fallback test; the saved mock modules are put
    back afterwards so later test files still see the conftest mock.
    """
    saved = {name: mod for name, mod in sys.modules.items()
             if name == "PIL" or name.startswith("PIL.")}
    for name in saved:
        del sys.modules[name]
    import PIL.Image  # noqa: F401 — real PIL, for the fallback under test
    yield
    for name in list(sys.modules):
        if name == "PIL" or name.startswith("PIL."):
            del sys.modules[name]
    sys.modules.update(saved)


def test_image_vary_with_fake_engine_returns_artifact(client, monkeypatch):
    h = _auth_headers(client)
    monkeypatch.setattr(image_ops, "get_engine", lambda: _FakeEngine())
    r = client.post("/api/image/vary", json={"image_b64": _png_bytes(), "strength": "strong"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["images"]


def test_image_unsupported_op_returns_422_not_fake_image(client, monkeypatch):
    h = _auth_headers(client)
    monkeypatch.setattr(image_ops, "get_engine", lambda: _BareEngine())
    r = client.post("/api/image/vary", json={"image_b64": _png_bytes()}, headers=h)
    assert r.status_code == 422, r.text
    assert "not supported" in r.text.lower()
    r = client.post("/api/image/inpaint",
                    json={"image_b64": _png_bytes(), "mask_b64": _png_bytes(),
                          "prompt": "repaint"}, headers=h)
    assert r.status_code == 422, r.text


def test_image_upscale_pillow_fallback_is_labelled(client, monkeypatch, real_pil):
    h = _auth_headers(client)
    monkeypatch.setattr(image_ops, "get_engine", lambda: _BareEngine())
    r = client.post("/api/image/upscale", json={"image_b64": _png_bytes(), "factor": 2.0}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["images"]
    assert "local resize, not AI upscaling" in body["method"]


def test_image_describe_with_no_model_returns_503(client, monkeypatch):
    h = _auth_headers(client)

    async def _no_model(db):
        return None

    monkeypatch.setattr(image_routes.llm, "default_model_id", _no_model)
    r = client.post("/api/image/describe", json={"image_b64": _png_bytes()}, headers=h)
    assert r.status_code == 503, r.text


def test_image_op_routes_exist(client):
    h = _auth_headers(client)
    for path in ("/api/image/vary", "/api/image/upscale", "/api/image/inpaint",
                 "/api/image/outpaint", "/api/image/image-prompt", "/api/image/describe"):
        r = client.post(path, json={}, headers=h)
        # Missing image_b64 -> 422 validation, never 404: the route exists.
        assert r.status_code == 422, (path, r.status_code, r.text)
