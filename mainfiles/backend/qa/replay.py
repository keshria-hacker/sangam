"""Replay recorded cases against a live app — no model call.

Each non-skipped case is re-issued through the supplied client and
compared (status + noise-normalized body) with the recorded exchange.
A case whose path is missing from the client (404 on a route that
was recorded as 200) fails with a diff, never silently passes.
``extra_headers`` / ``extra_kwargs`` let the caller supply fresh auth
at replay time (recorded headers are never stored, by design).
"""
from __future__ import annotations

from .noise import normalize_json


def _body_matches(recorded, actual, noise_fields) -> bool:
    if isinstance(recorded, dict) and isinstance(actual, dict):
        return (normalize_json(recorded, noise_fields)
                == normalize_json(actual, noise_fields))
    if isinstance(recorded, str) and isinstance(actual, str):
        from .noise import normalize_text
        return normalize_text(recorded) == normalize_text(actual)
    return recorded == actual


def replay_case(client, case: dict, extra_headers: dict | None = None) -> dict:
    if case.get("skip"):
        return {"case": case, "status": "skipped", "passed": None,
                "diff": "skipped at record time"}
    kwargs: dict = {}
    if extra_headers:
        kwargs["headers"] = extra_headers
    if case.get("request_body") is not None:
        kwargs["json"] = case["request_body"]
    try:
        resp = client.request(case["method"], case["path"], **kwargs)
    except Exception as exc:  # noqa: BLE001 — replay failure is a result
        return {"case": case, "status": "failed", "passed": False,
                "diff": f"request error: {exc}"}
    try:
        actual_body = resp.json()
    except Exception:
        actual_body = resp.text
    diffs = []
    if resp.status_code != case["status"]:
        diffs.append(f"status: recorded {case['status']}, got {resp.status_code}")
    if not _body_matches(case.get("response_body"), actual_body,
                         case.get("noise_fields") or []):
        diffs.append("body differs after noise normalization")
    if diffs:
        return {"case": case, "status": "failed", "passed": False,
                "diff": "; ".join(diffs),
                "actual_status": resp.status_code,
                "actual_body": actual_body}
    return {"case": case, "status": "passed", "passed": True, "diff": ""}


def replay_cases(client, cases: list[dict],
                 extra_headers: dict | None = None) -> list[dict]:
    return [replay_case(client, c, extra_headers=extra_headers)
            for c in (cases or [])]
