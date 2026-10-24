"""Wave-2 INFRA tests: cassettes, mDNS, pack updates, Fooocus controls.

Covers backend/cassette.py, backend/mdns.py, backend/pack_updates.py and
the Fooocus controls on the image-gen abstraction. No live network is
used anywhere here: upstream traffic is an httpx MockTransport, the
mDNS test parses locally-built packets, and the pack feed is a file://
fixture. No Playwright, no servers.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import httpx
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import backend.cassette as cassette_mod  # noqa: E402
from backend.cassette import (  # noqa: E402
    CassetteMiss,
    CassetteTransport,
    cassette_async_client,
    find_cassette,
    load_cassettes,
)
from backend.image_gen.engines import (  # noqa: E402
    FOOCUSS_CONTROL_FIELDS,
    FooocusControls,
    FooocusEngine,
    GeneratedImage,
    LoRARef,
    OpenAIImagesEngine,
    UnsupportedImageControl,
)
from backend.image_gen.styles import (  # noqa: E402
    expand_wildcards,
    parse_prompt_weights,
    prepare_prompt,
)
from backend.mdns import (  # noqa: E402
    MdnsAdvertiser,
    SERVICE_TYPE,
    build_announcement,
    instance_name,
    local_advertisement,
    parse_mdns_packet,
)
from backend.pack_updates import (  # noqa: E402
    check_installed_packs,
    check_pack_updates,
    compare_versions,
)
import backend.image_gen.service as svc  # noqa: E402


# ---------------------------------------------------------------------------
# Cassettes
# ---------------------------------------------------------------------------

DDG_HTML = ("<table><tr><td><a class='result-link' "
            "href='https://example.com/pricing'>Example Pricing</a></td>"
            "<td class='result-snippet'>Example snippet text</td></tr></table>")


def _mock_upstream(body: str = DDG_HTML, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body, request=request)
    return httpx.MockTransport(handler)


def test_cassette_record_then_replay_roundtrip(tmp_path):
    async def run():
        record = CassetteTransport(tmp_path, mode="record", upstream=_mock_upstream())
        async with httpx.AsyncClient(transport=record) as client:
            resp = await client.post("https://lite.duckduckgo.com/lite/",
                                     data={"q": "test", "kl": ""})
            assert resp.status_code == 200
        assert list(tmp_path.glob("*.yaml")), "record mode must write a YAML cassette"
        replay = CassetteTransport(tmp_path, mode="replay")
        async with httpx.AsyncClient(transport=replay) as client:
            resp = await client.post("https://lite.duckduckgo.com/lite/",
                                     data={"q": "test", "kl": ""})
            assert resp.status_code == 200
            assert "Example Pricing" in resp.text
    asyncio.run(run())


def test_cassette_replay_serves_websearch_without_live_network(tmp_path):
    """The flake-retirement proof: web_search through a cassette client
    returns parsed results with no live network (upstream is a mock)."""
    import backend.websearch as websearch
    from unittest.mock import patch

    async def run():
        record = CassetteTransport(tmp_path, mode="record", upstream=_mock_upstream())
        async with httpx.AsyncClient(transport=record) as client:
            await client.post("https://lite.duckduckgo.com/lite/",
                              data={"q": "openai api pricing", "kl": ""},
                              headers=websearch._DDG_HEADERS)
        orig = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs.pop("timeout", None)
            return orig(transport=CassetteTransport(tmp_path, mode="replay"))
        with patch("httpx.AsyncClient", factory):
            results = await websearch.web_search("openai api pricing", max_results=3)
        assert len(results) >= 1
        assert results[0].url.startswith("https")
        assert "Example" in results[0].title
    asyncio.run(run())


def test_committed_example_cassette_loads_and_matches():
    cassettes = load_cassettes(_ROOT / "tests" / "cassettes")
    names = [c.name for c in cassettes]
    assert "duckduckgo-lite-example" in names
    req = httpx.Request(
        "POST", "https://lite.duckduckgo.com/lite/",
        headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/120.0 Safari/537.36"},
        content=b"q=test&kl=")
    cas = find_cassette(req, cassettes)
    assert cas.response["status"] == 200
    assert "Example Pricing" in cas.response["body_text"]


def test_cassette_miss_names_the_stage(tmp_path):
    async def run():
        record = CassetteTransport(tmp_path, mode="record", upstream=_mock_upstream())
        async with httpx.AsyncClient(transport=record) as client:
            await client.post("https://lite.duckduckgo.com/lite/",
                              data={"q": "test", "kl": ""})
        replay = CassetteTransport(tmp_path, mode="replay")
        async with httpx.AsyncClient(transport=replay) as client:
            with pytest.raises(CassetteMiss) as excinfo:
                await client.post("https://example.com/other", data={"q": "x"})
            assert "stage: host-miss" in str(excinfo.value)
            with pytest.raises(CassetteMiss) as excinfo:
                await client.post("https://lite.duckduckgo.com/lite/",
                                  data={"q": "different", "kl": ""})
            assert "stage: query-miss" in str(excinfo.value) or "body-miss" in str(excinfo.value)
    asyncio.run(run())


def test_cassette_noise_fields_ignored(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "abc-123", "created": "2026-01-01",
                                         "value": 7}, request=request)
    async def run():
        async with httpx.AsyncClient(
                transport=CassetteTransport(tmp_path, mode="record",
                                            upstream=httpx.MockTransport(handler))) as client:
            await client.post("https://api.example.com/v1/chat",
                              json={"prompt": "hi", "created": "t0"})
        # Rewrite the recorded cassette's noise list, then replay with
        # different noise-field values: the match must still succeed.
        import yaml
        path = next(tmp_path.glob("*.yaml"))
        doc = yaml.safe_load(path.read_text())
        doc["noise"] = {"body_fields": ["created"]}
        path.write_text(yaml.safe_dump(doc))
        async with httpx.AsyncClient(transport=CassetteTransport(tmp_path, mode="replay")) as client:
            resp = await client.post("https://api.example.com/v1/chat",
                                     json={"prompt": "hi", "created": "t1"})
            assert resp.status_code == 200
    asyncio.run(run())


def test_cassette_record_refuses_secret_body(tmp_path):
    async def run():
        async with httpx.AsyncClient(
                transport=CassetteTransport(tmp_path, mode="record",
                                            upstream=_mock_upstream('{"api_key": "sk-secret"}'))) as client:
            with pytest.raises(RuntimeError, match="secret"):
                await client.get("https://api.example.com/v1/x")
        assert list(tmp_path.glob("*.yaml")) == []
    asyncio.run(run())


def test_cassette_async_client_off_is_plain():
    client = cassette_async_client(directory=None, mode="off")
    assert isinstance(client, httpx.AsyncClient)
    asyncio.run(client.aclose())


# ---------------------------------------------------------------------------
# mDNS
# ---------------------------------------------------------------------------

def test_mdns_packet_roundtrip():
    packet = build_announcement("Sangam-testhost", 8001, ["192.168.1.42"])
    peers = parse_mdns_packet(packet)
    assert len(peers) == 1
    peer = peers[0]
    assert peer["instance"] == "Sangam-testhost"
    assert peer["port"] == 8001
    assert "192.168.1.42" in peer["ips"]


def test_mdns_malformed_packet_is_empty_not_crash():
    assert parse_mdns_packet(b"\x00\x01") == []
    assert parse_mdns_packet(b"not a dns packet at all........") == []


def test_mdns_off_unless_enabled():
    adv = MdnsAdvertiser(8001, ips=["192.168.1.42"])
    assert adv.start(enabled=False) is False
    assert adv.running is False
    assert adv.status()["advertisement"] is None


def test_mdns_advertisement_shape():
    ad = local_advertisement(8001, ips=["192.168.1.42"], hostname="laptop")
    assert ad["service_type"] == SERVICE_TYPE
    assert ad["instance"] == "Sangam-laptop"
    assert ad["port"] == 8001
    assert ad["ips"] == ["192.168.1.42"]


def test_mdns_instance_name_sanitized():
    assert instance_name("my laptop!") == "Sangam-my-laptop-"


def test_mdns_advertiser_start_stop_gated():
    adv = MdnsAdvertiser(8001, ips=[])
    assert adv.start(enabled=True) is True
    assert adv.running is True
    assert adv.status()["advertisement"]["port"] == 8001
    adv.stop()
    assert adv.running is False


# ---------------------------------------------------------------------------
# Pack updates
# ---------------------------------------------------------------------------

def test_pack_version_comparison():
    assert compare_versions("1.10.0", "1.2.0") == 1
    assert compare_versions("1.2.0", "1.2.0") == 0
    assert compare_versions("1.2", "1.2.0") == 0
    assert compare_versions("0.9.9", "1.0.0") == -1


def test_pack_updates_from_local_feed(tmp_path):
    feed = tmp_path / "feed.json"
    feed.write_text('{"packs": {"engineering": {"version": "2.0.0", '
                    '"changelog_url": "https://example.com/eng/CHANGELOG.md"}, '
                    '"science-essentials": {"version": "1.0.0"}}}')
    report = check_pack_updates(
        [{"name": "engineering", "version": "1.0.0"},
         {"name": "science-essentials", "version": "1.0.0"},
         {"name": "not-in-feed", "version": "1.0.0"}],
        feed_url=f"file://{feed}")
    assert report.feed_ok is True
    by_name = {u.name: u for u in report.updates}
    assert by_name["engineering"].update_available is True
    assert by_name["engineering"].latest_version == "2.0.0"
    assert by_name["engineering"].changelog_url == "https://example.com/eng/CHANGELOG.md"
    assert by_name["science-essentials"].update_available is False
    assert by_name["not-in-feed"].in_feed is False


def test_pack_updates_no_feed_configured(monkeypatch):
    monkeypatch.delenv("SANGAM_PACK_FEED_URL", raising=False)
    report = check_pack_updates([{"name": "engineering", "version": "1.0.0"}])
    assert report.feed_ok is False
    assert "no pack feed configured" in report.error
    assert report.available == []  # reports, never invents updates


def test_pack_updates_bad_feed_is_soft_failure(tmp_path):
    feed = tmp_path / "feed.json"
    feed.write_text("not json at all")
    report = check_pack_updates([{"name": "engineering", "version": "1.0.0"}],
                                feed_url=f"file://{feed}")
    assert report.feed_ok is False
    assert report.available == []


def test_pack_updates_installed_packs_against_example_feed():
    # The committed example feed pins engineering at 9.9.9: any real
    # installed engineering pack is older, so it must show as available.
    feed = _ROOT / "tests" / "cassettes" / "pack-feed-example.json"
    report = check_installed_packs(feed_url=f"file://{feed}")
    assert report.feed_ok is True
    assert any(u.name == "engineering" and u.update_available
               for u in report.updates if u.in_feed)


# ---------------------------------------------------------------------------
# Fooocus controls
# ---------------------------------------------------------------------------

def test_prompt_weights_basic_and_bare():
    plain, segments = parse_prompt_weights("(cat:1.5) dog")
    assert plain == "cat dog"
    assert ("cat", 1.5) in segments
    plain, segments = parse_prompt_weights("(word) plain")
    assert plain == "word plain"
    assert ("word", 1.1) in segments


def test_prompt_weights_nested_multiply():
    plain, segments = parse_prompt_weights("((x))")
    assert plain == "x"
    assert segments == [("x", 1.21)]


def test_prompt_weights_unbalanced_is_literal():
    plain, segments = parse_prompt_weights("(oops plain")
    assert plain == "(oops plain"


def test_wildcards_file_based_and_seeded(tmp_path):
    wild_dir = tmp_path / "wildcards"
    wild_dir.mkdir()
    (wild_dir / "color.txt").write_text("# comment\nred\nblue\ngreen\n")
    first = expand_wildcards("a __color__ car", wildcards_dir=wild_dir, seed=42)
    second = expand_wildcards("a __color__ car", wildcards_dir=wild_dir, seed=42)
    assert first == second
    assert "__color__" not in first
    assert any(c in first for c in ("red", "blue", "green"))


def test_wildcards_in_order_cycles(tmp_path):
    wild_dir = tmp_path / "wildcards"
    wild_dir.mkdir()
    (wild_dir / "animal.txt").write_text("cat\ndog\n")
    out = expand_wildcards("__animal__ __animal__ __animal__",
                           wildcards_dir=wild_dir, in_order=True)
    assert out == "cat dog cat"


def test_wildcards_missing_file_left_verbatim():
    assert expand_wildcards("a __nope__ thing", wildcards_dir="/nonexistent") == "a __nope__ thing"


def test_wildcards_nested_expand(tmp_path):
    wild_dir = tmp_path / "wildcards"
    wild_dir.mkdir()
    (wild_dir / "outer.txt").write_text("__inner__ shade\n")
    (wild_dir / "inner.txt").write_text("deep\n")
    assert expand_wildcards("__outer__", wildcards_dir=wild_dir, in_order=True) == "deep shade"


def test_fooocus_controls_validation():
    with pytest.raises(ValueError, match="sampler"):
        FooocusControls(sampler="nope").validate()
    with pytest.raises(ValueError, match="clip_skip"):
        FooocusControls(clip_skip=13).validate()
    with pytest.raises(ValueError, match="LoRA"):
        FooocusControls(loras=[LoRARef(name="x", weight=3.0)]).validate()
    FooocusControls(sampler="dpmpp_2m_sde_gpu", scheduler="karras",
                    steps=20, cfg=7.0, seed=1, clip_skip=2,
                    loras=[LoRARef(name="detail", weight=-2.0)],
                    embeddings=["easynegative"]).validate()


def test_openai_engine_rejects_controls_without_network():
    with pytest.raises(UnsupportedImageControl):
        OpenAIImagesEngine().generate(
            "a cat", controls=FooocusControls(sampler="euler", steps=20))


def test_fooocus_engine_validates_before_connect():
    # Bad sampler must fail on validation, not on the missing Gradio server.
    with pytest.raises(ValueError, match="sampler"):
        FooocusEngine().generate("a cat", controls=FooocusControls(sampler="nope"))
    # Valid controls reach the (honest, still unmapped) Gradio path and
    # raise a diagnostic RuntimeError — real Fooocus is not available here.
    with pytest.raises(RuntimeError):
        FooocusEngine().generate(
            "a cat", controls=FooocusControls(sampler="euler", scheduler="karras"))


def test_service_forwards_controls_and_strips_weights(monkeypatch):
    class FakeEngine:
        name = "fake-fooocus"
        supported_controls = FOOCUSS_CONTROL_FIELDS

        def __init__(self):
            self.seen = None

        def is_available(self):
            return True

        def generate(self, prompt, negative_prompt="", size="1024x1024", n=1, controls=None):
            self.seen = (prompt, controls)
            return [GeneratedImage(b"fake-png", "image/png")]

    fake = FakeEngine()
    monkeypatch.setattr(svc, "_get_engine", lambda: fake)
    monkeypatch.setattr("backend.api_routes.media_routes.save_media_file",
                        lambda data, name, mime: f"saved:{name}")
    svc.reset_image_gen_for_testing()
    try:
        out = svc.generate_images(
            "(cat:1.5) in __color__ field",
            controls=FooocusControls(sampler="euler", scheduler="karras",
                                     steps=20, cfg=7.0, seed=7,
                                     loras=[LoRARef(name="detail", weight=0.8)],
                                     embeddings=["easynegative"]),
            wildcard_words={"color": ["red"]})
    finally:
        svc.reset_image_gen_for_testing()
    assert out == ["saved:generated_1.png"]
    prompt_seen, controls_seen = fake.seen
    assert "__color__" not in prompt_seen and "red" in prompt_seen
    assert "(cat:1.5)" not in prompt_seen and "cat" in prompt_seen
    assert controls_seen.sampler == "euler"
    assert controls_seen.prompt_weights, "weights must reach a supporting engine"


def test_service_weights_on_openai_engine_are_422_not_silent(monkeypatch):
    monkeypatch.setattr(svc, "_get_engine", lambda: OpenAIImagesEngine())
    svc.reset_image_gen_for_testing()
    try:
        with pytest.raises(UnsupportedImageControl):
            svc.generate_images("(cat:1.5) portrait")
    finally:
        svc.reset_image_gen_for_testing()


def test_service_sampler_on_openai_engine_is_422(monkeypatch):
    monkeypatch.setattr(svc, "_get_engine", lambda: OpenAIImagesEngine())
    svc.reset_image_gen_for_testing()
    try:
        with pytest.raises(UnsupportedImageControl):
            svc.generate_images("a cat", controls=FooocusControls(sampler="euler"))
    finally:
        svc.reset_image_gen_for_testing()


def test_image_status_lists_fooocus_controls(monkeypatch):
    monkeypatch.setattr(svc, "_get_engine", lambda: None)
    status = svc.image_status()
    controls = status["fooocus_controls"]
    assert "dpmpp_2m_sde_gpu" in controls["samplers"]
    assert "karras" in controls["schedulers"]
    assert controls["ranges"]["clip_skip"] == [1, 12]
    assert controls["ranges"]["lora_weight"] == [-2.0, 2.0]
