"""
End-to-end feature walkthrough for Sangam.

Starts nothing itself — run it while the app is up (python start.py), then:

    venv/Scripts/python.exe scripts/e2e_walkthrough.py

It exercises every feature the frontend uses, in the same order and with the
same headers (Bearer token + CSRF double-submit), and prints PASS/FAIL lines.
Exit code is 0 only when every check passes.
"""

import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8001/api"
USERNAME = "e2euser"
PASSWORD = "StrongPass!42"

failures: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name} {extra}")
    if not ok:
        failures.append(name)


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=60.0)

    # 1. public status
    r = c.get("/auth/status")
    check("GET /auth/status", r.status_code == 200)

    # 2. login (register on first run); retry briefly on rate limit
    import time

    r = c.post("/auth/register", json={"username": USERNAME, "password": PASSWORD})
    if r.status_code == 403:  # account already exists
        r = c.post("/auth/login", json={"username": USERNAME, "password": PASSWORD})
    for _ in range(5):
        if r.status_code != 429:
            break
        time.sleep(2)
        r = c.post("/auth/login", json={"username": USERNAME, "password": PASSWORD})
    check("register/login", r.status_code in (200, 201))
    if r.status_code not in (200, 201):
        return 1
    token = r.json()["access_token"]
    csrf = r.json().get("csrf_token") or c.cookies.get("sangam_csrf", "")
    H = {"Authorization": f"Bearer {token}"}      # GETs
    MUT = {**H, "X-CSRF-Token": csrf}             # mutations (frontend parity)

    # 3. session check
    r = c.get("/auth/me", headers=H)
    check("GET /auth/me", r.status_code == 200 and r.json().get("authenticated"))

    # 4. model selector
    r = c.get("/providers", headers=H)
    check("GET /providers", r.status_code == 200, str(r.json())[:60])
    r = c.get("/models", headers=H)
    check("GET /models", r.status_code == 200, f"{len(r.json())} models")
    models = r.json()
    for pid in sorted({m["provider"] for m in models}):
        r = c.get(f"/models/{pid}", headers=H)
        check(f"GET /models/{pid}", r.status_code == 200)

    # 5. provider key manager
    r = c.get("/settings/providers", headers=H)
    check("GET /settings/providers", r.status_code == 200, f"{len(r.json())} providers")
    r = c.put("/settings/providers/openai/key", headers=MUT,
              json={"api_key": "sk-test-1234567890abcdef"})
    check("PUT provider key", r.status_code == 200, r.json().get("masked_key", ""))
    r = c.get("/settings/providers/openai/models/refresh", headers=H)
    check("refresh models", r.status_code == 200, f"success={r.json().get('success')}")
    r = c.delete("/settings/providers/openai/key", headers=MUT)
    check("DELETE provider key", r.status_code == 204)

    # 6. response-style preferences
    r = c.put("/user/preferences", headers=MUT, json={
        "response_style": "concise", "formality": "casual", "expertise_level": "expert",
    })
    check("PUT preferences", r.status_code == 200, r.json().get("response_style", ""))
    r = c.get("/user/preferences", headers=H)
    check("GET preferences", r.status_code == 200, r.json().get("response_style", ""))

    # 7. chat streaming
    stream_req = {
        "chat_id": None,
        "model": models[0]["id"] if models else "ollama::llama3.2",
        "messages": [{"role": "user", "content": "Hello, quick smoke test"}],
        "file_ids": [], "temperature": 0.7, "max_tokens": 64,
        "regenerate": False, "web_search": False,
    }
    r = c.post("/chat/stream", headers=MUT, json=stream_req)
    ct = r.headers.get("content-type", "")
    check("POST /chat/stream (SSE)", r.status_code == 200 and "text/event-stream" in ct, ct)
    events = [ln for ln in r.text.splitlines() if ln.startswith("event:")]
    check("SSE chat_id event", "event: chat_id" in events, f"{len(events)} event lines")
    done, had_error = "[DONE]" in r.text, "event: error" in events
    check("stream completed or graceful error", done or had_error, f"done={done} error={had_error}")

    r = c.get("/chats", headers=H)
    chats = r.json()
    check("chat persisted", len(chats) >= 1, f"{len(chats)} chats")
    chat_id = chats[0]["id"] if chats else None
    if chat_id:
        r = c.get(f"/chats/{chat_id}", headers=H)
        check("GET /chats/{id}", r.status_code == 200, f"msgs={r.json().get('message_count')}")
        r = c.get(f"/chats/{chat_id}/summary", headers=H)
        check("GET chat summary", r.status_code == 200)

    # 8. file upload + RAG chat
    r = c.post("/files", headers=MUT,
               files={"file": ("note.txt", "Sangam e2e test file. " * 50, "text/plain")})
    check("POST /files", r.status_code == 200, f"preview={bool(r.json().get('preview'))}")
    file_id = r.json().get("file_id")
    if file_id and chat_id:
        stream_req.update(chat_id=chat_id, file_ids=[file_id])
        stream_req["messages"] = [{"role": "user", "content": "What does the attached note.txt say?"}]
        r = c.post("/chat/stream", headers=MUT, json=stream_req)
        check("chat with file (RAG)", r.status_code == 200
              and "text/event-stream" in r.headers.get("content-type", ""))

    # 9. web search
    r = c.get("/websearch", headers=H, params={"q": "python fastapi"})
    check("GET /websearch", r.status_code in (200, 502),
          f"provider={r.json().get('provider') if r.status_code == 200 else 'unreachable'}")

    # 10. skills
    r = c.get("/skills/", headers=H)
    check("GET /skills/", r.status_code == 200, f"{len(r.json())} skills")
    skills = r.json()
    r = c.get("/skills/categories", headers=H)
    check("GET /skills/categories", r.status_code == 200)
    if skills:
        r = c.get(f"/skills/{skills[0]['id']}", headers=H)
        check("GET /skills/{id}", r.status_code == 200)

    # 11. agentic reasoning (tool use)
    r = c.post("/agentic-reasoning", headers=MUT, json={
        "message": "search for the latest fastapi release news",
        "model": models[0]["id"] if models else "",
        "max_iterations": 2, "tools": ["web_search"],
    })
    ok = r.status_code == 200 and "enhanced_message" in r.json()
    check("POST /agentic-reasoning", ok,
          f"reasoning_used={r.json().get('reasoning_used') if r.status_code == 200 else r.status_code}")

    # 12. inaccessible-model cache
    r = c.post("/models/inaccessible/clear", headers=MUT)
    check("POST /models/inaccessible/clear", r.status_code == 204)

    # 13. message feedback
    if chat_id:
        r = c.get(f"/chats/{chat_id}", headers=H)
        assistant = next(
            (m for m in r.json().get("messages", []) if m["role"] == "assistant"), None)
        if assistant:
            r = c.post(f"/messages/{assistant['id']}/feedback", headers=MUT, json={"value": "up"})
            check("POST feedback", r.status_code == 200, str(r.json().get("feedback")))
            r = c.post(f"/messages/{assistant['id']}/feedback", headers=MUT, json={"value": "up"})
            check("feedback toggle-off", r.status_code == 200 and r.json()["feedback"] is None)

    # 14. delete chat + logout
    if chat_id:
        r = c.delete(f"/chats/{chat_id}", headers=MUT)
        check("DELETE /chats/{id}", r.status_code == 204)
    r = c.post("/auth/logout", headers=MUT)
    check("POST /auth/logout", r.status_code in (200, 204))

    c.close()
    print(f"\n{len(failures)} failure(s)" if failures else "\nAll checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
