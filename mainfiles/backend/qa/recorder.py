"""Record real API traffic into deterministic cassettes.

A case is one exchange: method, path, request body, status, response
body, plus the noise fields declared at record time. Headers that
carry secrets (authorization, api keys, cookies, CSRF) are redacted
to ``<redacted>`` and never stored; the replay caller supplies fresh
auth headers at replay time.

Cassettes are plain JSON (not YAML — the provider cassette layer in
``backend/cassette.py`` already owns YAML; QA cassettes are a
separate, API-test-shaped format and say so, to avoid confusion).
"""
from __future__ import annotations

import json
from pathlib import Path

SECRET_HEADERS = {"authorization", "x-api-key", "api-key", "cookie",
                  "x-csrf-token", "set-cookie"}
SECRET_BODY_KEYS = {"password", "api_key", "api-key", "secret", "token"}


def _redact_body(body):
    if isinstance(body, dict):
        return {k: ("<redacted>" if k.lower() in SECRET_BODY_KEYS else _redact_body(v))
                for k, v in body.items()}
    if isinstance(body, list):
        return [_redact_body(v) for v in body]
    return body


class Recorder:
    def __init__(self):
        self.cases: list[dict] = []

    def record(self, method: str, path: str, request_body=None,
               status: int = 200, response_body=None,
               noise_fields: list[str] | None = None,
               skip: bool = False) -> dict:
        case = {
            "method": method.upper(), "path": path,
            "request_body": _redact_body(request_body),
            "status": int(status),
            "response_body": _redact_body(response_body),
            "noise_fields": list(noise_fields or []),
            "skip": bool(skip),
        }
        self.cases.append(case)
        return case

    def record_response(self, client, method: str, path: str, **kwargs):
        """Record one real exchange through a TestClient-like client.

        ``kwargs`` may carry ``noise_fields`` and ``skip`` (popped
        before the request) plus any TestClient request kwargs
        (json, headers, ...). Returns (case, response).
        """
        noise_fields = kwargs.pop("noise_fields", None)
        skip = kwargs.pop("skip", False)
        resp = client.request(method, path, **kwargs)
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        req_body = kwargs.get("json", kwargs.get("data"))
        case = self.record(method, path, request_body=req_body,
                           status=resp.status_code, response_body=body,
                           noise_fields=noise_fields, skip=skip)
        return case, resp

    def to_dict(self) -> dict:
        return {"version": 1, "cases": self.cases}


def save_cassette(recorder_or_cases, path: Path | str) -> Path:
    cases = (recorder_or_cases.cases if isinstance(recorder_or_cases, Recorder)
             else recorder_or_cases)
    data = {"version": 1, "cases": list(cases)}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return p


def load_cassette(path: Path | str) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        if data.get("version") != 1:
            raise ValueError(f"unsupported QA cassette version: {data.get('version')}")
        return list(data.get("cases") or [])
    raise ValueError("QA cassette must be a JSON object with version + cases")
