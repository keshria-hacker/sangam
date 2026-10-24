"""
cassette.py — HTTP cassette layer (Keploy pattern, WITHOUT eBPF).

Keploy records real dependency traffic at the kernel boundary and replays
it from a YAML registry, with a noise model for fields that legitimately
vary and a closest-match diff when replay misses. Sangam cannot use
Keploy's capture plane (privileged, Linux-only eBPF), so this module
ports only the portable half: a recording/replaying httpx transport
over YAML cassettes committed under ``tests/cassettes/``.

Scope and honesty:
- This is a TEST transport, not a production proxy. Nothing in the
  production code path reads these cassettes unless a caller explicitly
  builds a client through :func:`cassette_async_client` (or passes a
  :class:`CassetteTransport`). Provider and websearch call sites still
  construct plain ``httpx.AsyncClient`` instances; wiring this transport
  into them is a separate, parent-owned step (see BUILD_LOG2-infra.md).
  What this module proves today: a recorded DuckDuckGo-Lite exchange
  replays through ``backend.websearch.web_search`` with no live network
  (tests/test_deep_infra.py), so the live-network flake in
  tests/test_websearch.py *can* be retired once that wiring lands.
- Sync ``httpx.post/get`` call sites (image engines) are NOT covered:
  this transport is async-only. They are recorded in the build log as
  remaining work, not silently claimed.
- Recording never truncates: a body over ``MAX_BODY_BYTES`` aborts the
  recording with an error instead of writing a partial cassette
  (Keploy's over-budget rule).

Modes (``SANGAM_CASSETTE_MODE`` env, or explicit constructor arg):
- ``replay``: serve recorded exchanges; a miss raises
  :class:`CassetteMiss` whose message names the exact stage it died at.
- ``record``: forward to the upstream transport and write one YAML
  file per exchange.
- ``off``: pass through with no recording (default when unset).

A cassette file (``<name>.yaml``)::

    version: 1
    request:
      method: POST
      url: https://lite.duckduckgo.com/lite/
      headers: {user-agent: "..."}
      body: "q=openai+api+pricing&kl="
    response:
      status: 200
      headers: {content-type: "text/html; charset=utf-8"}
      body_text: "<html>..."
    noise:
      headers: [date, x-request-id]
      body_fields: ["data.id", "created"]

Noise semantics: ``noise.headers`` are stripped from the fingerprint
on both sides; ``noise.body_fields`` are dot-paths removed from JSON
bodies before comparison (``*`` matches any dict key / list item).
Secrets must never be recorded: request headers in
``SECRET_HEADERS`` are redacted to ``<redacted>`` at write time, and
record mode refuses to write a cassette whose body contains an
``api_key``-style field unless the caller passes ``allow_secrets=True``
(explicit, test-only).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlparse, urlunparse

import httpx
import yaml

logger = logging.getLogger(__name__)

CASSETTE_VERSION = 1
MAX_BODY_BYTES = 1_000_000  # Keploy-style byte budget: over budget aborts, never truncates.

DEFAULT_NOISE_HEADERS = frozenset({
    "date", "x-request-id", "request-id", "cf-ray", "x-cloud-trace-context",
    "set-cookie", "etag", "last-modified", "age", "x-response-time",
})
SECRET_HEADERS = frozenset({"authorization", "x-api-key", "api-key", "x-subscription-token"})
_SECRET_BODY_KEYS = re.compile(r"(api[_-]?key|secret|token|password)", re.I)

ENV_MODE = "SANGAM_CASSETTE_MODE"
ENV_DIR = "SANGAM_CASSETTE_DIR"


def cassette_mode() -> str:
    """Effective mode: env var, else 'off'. Never auto-activates in prod."""
    mode = os.environ.get(ENV_MODE, "off").strip().lower()
    return mode if mode in ("replay", "record", "off") else "off"


def cassette_dir() -> Path:
    raw = os.environ.get(ENV_DIR, "")
    if raw:
        return Path(raw)
    # Default location, relative to this file's repo (mainfiles/backend -> repo root).
    return Path(__file__).resolve().parents[2] / "tests" / "cassettes"


# ---------------------------------------------------------------------------
# Fingerprinting + noise
# ---------------------------------------------------------------------------

def _strip_noise_value(value, path_parts: list[str]) -> object:
    """Remove noise dot-paths from a decoded JSON value. ``*`` is a wildcard."""
    if not path_parts:
        return value
    head, *rest = path_parts
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if head == "*" or head == key:
                if not rest:
                    continue  # this whole field is noise: drop it
                out[key] = _strip_noise_value(item, rest)
            else:
                out[key] = item
        return out
    if isinstance(value, list):
        if head == "*":
            return [_strip_noise_value(item, rest) for item in value]
        return value
    return value


def _strip_noise_fields(body: bytes, noise_fields: list[str]):
    """Return a canonical JSON string with noise fields removed, or the
    raw text when the body is not JSON."""
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return body.decode("utf-8", errors="replace")
    for path in noise_fields:
        data = _strip_noise_value(data, path.split("."))
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


# Transport-derived headers: httpx sets these itself, so they must not
# be part of a fingerprint — otherwise a hand-written cassette (or a
# cassette recorded under a different httpx version) can never match.
_TRANSPORT_HEADERS = frozenset(
    {"host", "content-length", "connection", "accept", "accept-encoding"})


def _canonical_headers(headers, noise_headers) -> dict:
    noise = {h.lower() for h in noise_headers}
    out = {}
    for key, value in dict(headers).items():
        lk = key.lower()
        if lk in noise or lk in _TRANSPORT_HEADERS:
            continue
        out[lk] = "<redacted>" if lk in SECRET_HEADERS else value
    return out


@dataclass(frozen=True)
class RequestFingerprint:
    method: str
    host: str
    path: str
    query: tuple
    headers: tuple
    body: str

    @classmethod
    def from_httpx(cls, request: httpx.Request, noise_headers, noise_fields) -> "RequestFingerprint":
        parsed = urlparse(str(request.url))
        query = tuple(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
        clean_path = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        body = _strip_noise_fields(request.content or b"", noise_fields)
        headers = tuple(sorted(_canonical_headers(request.headers, noise_headers).items()))
        return cls(request.method.upper(), parsed.netloc.lower(), parsed.path,
                   query, headers, body)

    @classmethod
    def from_cassette(cls, record: dict, noise_headers, noise_fields) -> "RequestFingerprint":
        req = record.get("request", {})
        parsed = urlparse(req.get("url", ""))
        query = tuple(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
        body_raw = req.get("body", "")
        body = _strip_noise_fields(body_raw.encode("utf-8"), noise_fields) \
            if isinstance(body_raw, str) else ""
        headers = tuple(sorted(_canonical_headers(req.get("headers", {}), noise_headers).items()))
        return cls(str(req.get("method", "GET")).upper(), parsed.netloc.lower(),
                   parsed.path, query, headers, body)


@dataclass
class Cassette:
    name: str
    request: dict
    response: dict
    noise_headers: list[str] = field(default_factory=list)
    noise_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        doc: dict = {
            "version": CASSETTE_VERSION,
            "request": self.request,
            "response": self.response,
        }
        if self.noise_headers:
            doc["noise"] = {"headers": self.noise_headers}
        if self.noise_fields:
            doc.setdefault("noise", {})["body_fields"] = self.noise_fields
        return doc

    @classmethod
    def from_dict(cls, name: str, doc: dict) -> "Cassette":
        noise = doc.get("noise", {}) or {}
        return cls(
            name=name,
            request=doc.get("request", {}),
            response=doc.get("response", {}),
            noise_headers=list(noise.get("headers", [])),
            noise_fields=list(noise.get("body_fields", [])),
        )


def load_cassettes(directory: Path) -> list[Cassette]:
    """Load every ``*.yaml`` cassette in a directory (sorted, deterministic)."""
    out = []
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            logger.warning("cassette %s unreadable, skipping: %s", path, exc)
            continue
        if doc.get("version") != CASSETTE_VERSION:
            logger.warning("cassette %s has unknown version %r, skipping", path, doc.get("version"))
            continue
        out.append(Cassette.from_dict(path.stem, doc))
    return out


def save_cassette(directory: Path, cassette: Cassette) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{cassette.name}.yaml"
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(cassette.to_dict(), sort_keys=False, allow_unicode=True),
                   encoding="utf-8")
    tmp.replace(path)  # atomic rename, same as Keploy's FileStore
    return path


# ---------------------------------------------------------------------------
# Miss diagnostics — the miss must name the exact stage it died at
# ---------------------------------------------------------------------------

class CassetteMiss(RuntimeError):
    """Raised in replay mode when no cassette matches. The message is a
    staged diagnosis, not a bare 'no match'."""


def _closest_diff(want: RequestFingerprint, cassettes: list[Cassette]) -> str:
    if not cassettes:
        return "stage: no-cassettes — the cassette directory holds no YAML files"
    scored = []
    for cas in cassettes:
        noise_h = set(DEFAULT_NOISE_HEADERS) | {h.lower() for h in cas.noise_headers}
        got = RequestFingerprint.from_cassette(cas.to_dict(), noise_h, cas.noise_fields)
        score = 0
        if got.host == want.host:
            score += 2
        if got.path == want.path:
            score += 3
        if got.method == want.method:
            score += 1
        if got.query == want.query:
            score += 1
        scored.append((score, cas.name, got))
    scored.sort(key=lambda t: -t[0])
    best_score, best_name, best = scored[0]
    if best.host != want.host:
        return (f"stage: host-miss — no cassette for host {want.host!r} "
                f"(closest: {best_name!r} for host {best.host!r})")
    if best.path != want.path:
        return (f"stage: path-miss — host {want.host!r} has no cassette for "
                f"path {want.path!r} (closest: {best_name!r} for {best.path!r})")
    if best.method != want.method:
        return (f"stage: method-miss — cassette {best_name!r} is {best.method}, "
                f"request is {want.method}")
    if best.query != want.query:
        return (f"stage: query-miss — cassette {best_name!r} query {dict(best.query)} "
                f"!= request query {dict(want.query)}")
    if best.body != want.body:
        # Name the first differing JSON field when both sides are JSON.
        try:
            a, b = json.loads(best.body), json.loads(want.body)
            if isinstance(a, dict) and isinstance(b, dict):
                for key in sorted(set(a) | set(b)):
                    if a.get(key) != b.get(key):
                        return (f"stage: body-miss — cassette {best_name!r} differs "
                                f"at body field {key!r} (recorded {a.get(key)!r} vs "
                                f"request {b.get(key)!r}); declare it in noise.body_fields "
                                f"if it legitimately varies")
        except (ValueError, TypeError):
            pass
        return (f"stage: body-miss — cassette {best_name!r} body differs from "
                f"the request body (compare the cassette file with the live request)")
    return (f"stage: header-miss — cassette {best_name!r} headers "
            f"{dict(best.headers)} != request headers {dict(want.headers)}")


def find_cassette(request: httpx.Request, cassettes: list[Cassette]) -> Cassette:
    """Exact fingerprint match under the union of default + per-cassette noise."""
    for cas in cassettes:
        noise_h = set(DEFAULT_NOISE_HEADERS) | {h.lower() for h in cas.noise_headers}
        want = RequestFingerprint.from_httpx(request, noise_h, cas.noise_fields)
        got = RequestFingerprint.from_cassette(cas.to_dict(), noise_h, cas.noise_fields)
        if want == got:
            return cas
    want = RequestFingerprint.from_httpx(request, DEFAULT_NOISE_HEADERS, [])
    raise CassetteMiss(_closest_diff(want, cassettes))


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------

def _response_from_cassette(request: httpx.Request, cas: Cassette) -> httpx.Response:
    resp = cas.response
    body = resp.get("body_text")
    if body is None and resp.get("body_b64") is not None:
        content = base64.b64decode(resp["body_b64"])
    elif isinstance(body, str):
        content = body.encode("utf-8")
    else:
        content = b""
    return httpx.Response(
        int(resp.get("status", 200)),
        headers=dict(resp.get("headers", {})),
        content=content,
        request=request,
    )


def cassette_name_for(request: httpx.Request) -> str:
    """Deterministic default name: method + host + path hash (no secrets)."""
    parsed = urlparse(str(request.url))
    digest = hashlib.sha256(f"{request.method}:{parsed.netloc}:{parsed.path}".encode()).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9]+", "-", parsed.path.strip("/").lower()) or "root"
    return f"{request.method.lower()}-{parsed.netloc}-{slug}-{digest}"


class CassetteTransport(httpx.AsyncBaseTransport):
    """httpx async transport with replay/record modes.

    ``upstream`` defaults to a real HTTP transport; tests pass a
    ``MockTransport`` so record mode never touches the network either.
    """

    def __init__(self, directory: Path | str, mode: str = "replay",
                 upstream: httpx.AsyncBaseTransport | None = None,
                 allow_secrets: bool = False):
        if mode not in ("replay", "record", "off"):
            raise ValueError(f"unknown cassette mode {mode!r}")
        self.directory = Path(directory)
        self.mode = mode
        self.upstream = upstream or httpx.AsyncHTTPTransport()
        self.allow_secrets = allow_secrets

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.mode == "off":
            return await self.upstream.handle_async_request(request)
        if self.mode == "replay":
            cassettes = load_cassettes(self.directory)
            cas = find_cassette(request, cassettes)
            return _response_from_cassette(request, cas)
        # record
        response = await self.upstream.handle_async_request(request)
        body = await response.aread()
        if len(body) > MAX_BODY_BYTES:
            raise RuntimeError(
                f"cassette record aborted: body {len(body)} bytes over budget "
                f"{MAX_BODY_BYTES} (over-budget capture aborts, never truncates)")
        body_text = body.decode("utf-8", errors="replace")
        if not self.allow_secrets and _SECRET_BODY_KEYS.search(body_text):
            raise RuntimeError(
                "cassette record refused: response body looks like it contains "
                "a secret field (api_key/secret/token/password); re-record with "
                "allow_secrets=True only if you have inspected the payload")
        headers = _canonical_headers(request.headers, DEFAULT_NOISE_HEADERS)
        cas = Cassette(
            name=cassette_name_for(request),
            request={
                "method": request.method,
                "url": str(request.url),
                "headers": headers,
                "body": (request.content or b"").decode("utf-8", errors="replace"),
            },
            response={
                "status": response.status_code,
                "headers": dict(response.headers),
                "body_text": body_text,
            },
        )
        save_cassette(self.directory, cas)
        return httpx.Response(response.status_code, headers=response.headers,
                              content=body, request=request)

    async def aclose(self) -> None:
        await self.upstream.aclose()


def cassette_async_client(directory: Path | str | None = None,
                          mode: str | None = None,
                          timeout: float | httpx.Timeout = 20.0,
                          upstream: httpx.AsyncBaseTransport | None = None,
                          **kwargs) -> httpx.AsyncClient:
    """Build an AsyncClient behind the cassette transport.

    This is the single construction point provider/websearch call sites
    should use when cassette wiring lands: today it is used by tests
    (via monkeypatching) and by any future caller that opts in.
    With mode='off' (or no directory) it is a plain client.
    """
    mode = mode or cassette_mode()
    if mode == "off" or directory is None:
        return httpx.AsyncClient(timeout=timeout, **kwargs)
    transport = CassetteTransport(directory, mode=mode, upstream=upstream)
    return httpx.AsyncClient(transport=transport, timeout=timeout, **kwargs)
