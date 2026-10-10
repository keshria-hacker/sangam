"""A4 regression: OmniRoute model sync must call fetch with a matching signature.

The old caller passed (api_key, config) to llm.fetch_models_from_provider,
which expects the legacy flat signature (api_key, endpoint_url,
provider_id, provider_label, ...) — so "Sync models" always raised
"missing 2 required positional arguments".

This test runs a fake OpenAI-compatible /models server locally and calls the
real provider fetch against it. No mocks of the function under test.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "mainfiles")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ["TEST_MODE"] = "1"


class _ModelsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        assert self.path == "/models", self.path
        # OpenAI-compatible models payload
        body = json.dumps({
            "data": [
                {"id": "fake-llm-1", "object": "model"},
                {"id": "fake-llm-2", "object": "model"},
            ]
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_fetch_models_from_provider_against_fake_server():
    import asyncio

    from backend.providers.base import ProviderConfig
    from backend.providers.model_discovery import fetch_models_from_provider

    server = HTTPServer(("127.0.0.1", 0), _ModelsHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = ProviderConfig(
            provider_id="omniroute",
            label="OmniRoute",
            local=True,
            env_key_name="",
            api_base=f"http://127.0.0.1:{port}",
            model_endpoint=f"http://127.0.0.1:{port}/models",
            auth_type="bearer",
            json_path="data",
            id_field="id",
            litellm_prefix="openai/",
        )
        models = asyncio.run(fetch_models_from_provider("fake-key", config))
    finally:
        server.shutdown()
        thread.join()

    ids = [m.id for m in models]
    assert "omniroute::openai/fake-llm-1" in ids, ids
    assert "omniroute::openai/fake-llm-2" in ids, ids


def test_omniroute_sync_route_uses_matching_signature():
    """The /omniroute/sync route must import the 2-arg fetch, not the legacy one."""
    import inspect

    import backend.api_routes.omniroute_routes as routes

    src = inspect.getsource(routes)
    # Must call the directly-imported 2-arg fetch...
    assert "fetch_models_from_provider(api_key, config)" in src
    # ...not the legacy llm adapter with the same call shape.
    assert "llm.fetch_models_from_provider(api_key, config)" not in src
