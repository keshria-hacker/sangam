"""
sangam_client.py — Phase 5: the official Python SDK (stdlib only).

A thin, dependency-free client over the versioned API (``/api/v1``):
health, workflows, knowledge retrieve, media jobs, runs. Auth is a
Bearer token from ``SANGAM_TOKEN`` (or passed explicitly); the base
URL comes from ``SANGAM_URL`` (default http://127.0.0.1:8001).

The CLI (``cli.py``) is a thin wrapper over this client, so anything
the CLI can do, an embedding script can do with the same calls.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class SangamError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


class SangamClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or os.environ.get("SANGAM_URL", "http://127.0.0.1:8001")).rstrip("/")
        self.token = token or os.environ.get("SANGAM_TOKEN", "")

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self.base_url}/api/v1{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raise SangamError(exc.code, exc.read().decode()) from None

    def health(self) -> dict:
        # /health is outside /api/v1, so call it directly.
        req = urllib.request.Request(f"{self.base_url}/health")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    def list_workflows(self) -> list:
        return self._request("GET", "/workflows").get("workflows", [])

    def run_workflow(self, workflow_id: str, input_data: dict | None = None,
                     idempotency_key: str | None = None) -> dict:
        body: dict = {"input": input_data or {}}
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request("POST", f"/workflows/{workflow_id}/run", body)

    def retrieve(self, query: str, top_k: int = 5) -> list:
        return self._request("GET", f"/knowledge/retrieve?q={_quote(query)}&top_k={top_k}").get("results", [])

    def list_media_jobs(self) -> list:
        return self._request("GET", "/media-jobs").get("jobs", [])

    def create_media_job(self, kind: str, **kwargs) -> dict:
        return self._request("POST", "/media-jobs", {"kind": kind, **kwargs})

    def list_runs(self) -> list:
        return self._request("GET", "/runs").get("runs", [])


def _quote(text: str) -> str:
    from urllib.parse import quote

    return quote(text)
