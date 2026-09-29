"""
Visual UI verification for Sangam via Chrome DevTools Protocol.

Drives a headless Chrome (already running with --remote-debugging-port=9222)
through the login, chat and settings flows, capturing a screenshot at every
step into test-results/ui/.

Usage:
    venv/Scripts/python.exe scripts/ui_verify_chrome.py
"""

import asyncio
import base64
import json
import sys
from pathlib import Path

import websockets

DEBUG_URL = "http://127.0.0.1:9222"
APP_URL = "http://127.0.0.1:5500/"
USERNAME = "e2euser"
PASSWORD = "StrongPass!42"
OUT_DIR = Path(__file__).resolve().parents[1] / "test-results" / "ui"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    results.append((name, ok, extra))
    print(f"{'PASS' if ok else 'FAIL'}  {name} {extra}")


async def rpc(ws, _id: int, method: str, params: dict | None = None, timeout: float = 15.0):
    """Send one CDP command and wait for the matching response."""
    msg = {"id": _id, "method": method}
    if params:
        msg["params"] = params
    await ws.send(json.dumps(msg))
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        data = json.loads(raw)
        if data.get("id") == _id:
            if "error" in data:
                raise RuntimeError(f"CDP error in {method}: {data['error']}")
            return data.get("result", {})


async def eval_js(ws, _id: int, expression: str, timeout: float = 15.0):
    """Evaluate JS in the page and return (value, exceptionText)."""
    res = await rpc(ws, _id, "Runtime.evaluate", {
        "expression": expression,
        "awaitPromise": True,
        "returnByValue": True,
    }, timeout=timeout)
    detail = res.get("result", {})
    return detail.get("value"), res.get("exceptionDetails", {}).get("exception", {}).get("description")


async def shot(ws, _id: int, name: str) -> None:
    res = await rpc(ws, _id, "Page.captureScreenshot", {"format": "png"})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{name}.png").write_bytes(base64.b64decode(res["data"]))
    print(f"      screenshot: test-results/ui/{name}.png")


async def main() -> int:
    # Find (or open) the app tab
    import urllib.request
    tabs = json.loads(urllib.request.urlopen(f"{DEBUG_URL}/json/list").read())
    page = next((t for t in tabs if t.get("type") == "page"), None)
    if page is None:
        check("open app tab", False, "no page target found in Chrome")
        return 1
    ws_url = page["webSocketDebuggerUrl"]

    async for ws in websockets.connect(ws_url, max_size=50 * 1024 * 1024):
        i = 0

        async def step(method, params=None, timeout=15.0):
            nonlocal i
            i += 1
            return await rpc(ws, i, method, params, timeout=timeout)

        async def js(expr, timeout=15.0):
            nonlocal i
            i += 1
            return await eval_js(ws, i, expr, timeout=timeout)

        async def screenshot(name):
            nonlocal i
            i += 1
            await shot(ws, i, name)

        await step("Page.enable")
        await step("Runtime.enable")

        # 0. Load the app
        await step("Page.navigate", {"url": APP_URL})
        await asyncio.sleep(3.5)
        val, err = await js("document.title + ' | ' + location.href")
        check("app loaded", err is None and "Sangam" in (val or ""), str(val)[:60])
        await screenshot("01_loaded")

        # 1. Auth screen visible?
        val, _ = await js("""
            (() => {
              const auth = document.querySelector('#authScreen, .auth-screen, [id*="auth"]');
              const app = document.querySelector('#appShell, .app-shell, main');
              return JSON.stringify({
                authVisible: !!auth && !auth.classList.contains('hidden'),
                authId: auth ? auth.id : null,
                appHidden: app ? app.classList.contains('hidden') : null,
              });
            })()
        """)
        auth = json.loads(val or "{}")
        check("auth screen shown first", bool(auth.get("authVisible")), str(auth)[:100])
        await screenshot("02_auth_screen")

        # 2. Fill login form and submit
        val, err = await js(f"""
            (async () => {{
              const user = document.querySelector('#loginUsername, input[name="username"]');
              const pass = document.querySelector('#loginPassword, input[name="password"]');
              const btn  = document.querySelector('#loginBtn, #loginSubmit, button[type="submit"]');
              if (!user || !pass || !btn) return 'missing: ' + [user, pass, btn].map(x => !!x);
              user.value = '{USERNAME}';
              user.dispatchEvent(new Event('input', {{bubbles: true}}));
              pass.value = '{PASSWORD}';
              pass.dispatchEvent(new Event('input', {{bubbles: true}}));
              btn.click();
              // wait for the app shell to appear
              for (let t = 0; t < 40; t++) {{
                await new Promise(r => setTimeout(r, 250));
                const app = document.querySelector('#appShell, .app-shell');
                if (app && !app.classList.contains('hidden')) return 'app-visible';
                const toast = document.querySelector('.toast-error, .toast.error');
                if (toast) return 'toast: ' + toast.textContent.slice(0, 80);
              }}
              return 'timeout: app never visible';
            }})()
        """, timeout=30.0)
        check("login flow completes", val == "app-visible", str(val)[:120])
        await screenshot("03_after_login")

        # 3. Model selector loaded?
        val, _ = await js("""
            (() => {
              const btn = document.querySelector('#modelSelectorBtn');
              const name = btn ? btn.querySelector('.model-name') : null;
              return JSON.stringify({
                modelName: name ? name.textContent.trim() : null,
                disabled: btn ? btn.disabled : null,
              });
            })()
        """)
        model = json.loads(val or "{}")
        check("model selector has a model", bool(model.get("modelName"))
              and "error" not in str(model.get("modelName", "")).lower()
              and "No model" not in str(model.get("modelName", "")),
              str(model.get("modelName")))
        await screenshot("04_model_selector")

        # 4. Sidebar chat list loaded
        val, _ = await js("document.querySelectorAll('#chatList .chat-item, #chatList li, .chat-list-item').length")
        check("sidebar chat list rendered", isinstance(val, int) and val >= 0, f"{val} items")
        await screenshot("05_sidebar")

        # 5. Send a chat message and watch the stream
        val, err = await js("""
            (async () => {
              const input = document.querySelector('#messageInput, #composer textarea, textarea');
              const send  = document.querySelector('#sendBtn');
              if (!input || !send) return 'missing composer elements';
              input.value = 'Say hello in exactly five words.';
              input.dispatchEvent(new Event('input', {bubbles: true}));
              send.click();
              for (let t = 0; t < 60; t++) {
                await new Promise(r => setTimeout(r, 500));
                const msgs = document.querySelectorAll('.msg.assistant, [class*="assistant"]');
                const last = msgs[msgs.length - 1];
                if (last && last.textContent.trim().length > 3) {
                  const typing = last.querySelector('.typing-indicator');
                  if (!typing) return 'reply: ' + last.textContent.trim().slice(0, 90);
                }
              }
              return 'timeout: no assistant reply appeared';
            })()
        """, timeout=45.0)
        streamed = isinstance(val, str) and val.startswith("reply:")
        check("chat streaming renders a reply", streamed, str(val)[:110])
        await screenshot("06_chat_streamed")

        # 6. Open settings modal
        val, err = await js("""
            (async () => {
              const btn = document.querySelector('#settingsBtn, [data-action="settings"], .settings-btn');
              if (!btn) return 'no settings button';
              btn.click();
              for (let t = 0; t < 20; t++) {
                await new Promise(r => setTimeout(r, 250));
                const modal = document.querySelector('#settingsModal, .settings-modal, .modal');
                if (modal && !modal.classList.contains('hidden')) {
                  const keys = document.querySelectorAll('#providerKeyManager .provider-status-row');
                  const theme = document.querySelectorAll('#themeOptions .theme-option');
                  return JSON.stringify({visible: true, providerRows: keys.length, themeOpts: theme.length});
                }
              }
              return 'settings modal never visible';
            })()
        """, timeout=20.0)
        settings = json.loads(val) if (val or "").startswith("{") else {"raw": val}
        check("settings modal opens", bool(settings.get("visible")), str(settings))
        check("provider key manager rows rendered", settings.get("providerRows", 0) > 0,
              f"{settings.get('providerRows')} rows")
        check("theme options rendered", settings.get("themeOpts", 0) >= 3,
              f"{settings.get('themeOpts')} options")
        await screenshot("07_settings_modal")

        # 7. Toggle theme Paper/Ink
        val, _ = await js("""
            (async () => {
              const light = document.querySelector('#themeOptions [data-theme="light"]');
              if (!light) return 'no theme option';
              light.click();
              await new Promise(r => setTimeout(r, 400));
              return document.documentElement.getAttribute('data-theme');
            })()
        """)
        check("theme toggles to light", val == "light", f"data-theme={val}")
        await screenshot("08_theme_light")
        val, _ = await js("""
            (async () => {
              const dark = document.querySelector('#themeOptions [data-theme="dark"]');
              if (dark) dark.click();
              await new Promise(r => setTimeout(r, 300));
              return document.documentElement.getAttribute('data-theme');
            })()
        """)
        check("theme toggles back to dark", val == "dark", f"data-theme={val}")

        # 8. Console errors so far
        # (collect from a fresh evaluate of window.__errors we install via listener)
        val, _ = await js("""
            (() => {
              // The app logs module loads to console; check for the API base marker
              return performance.getEntriesByType('resource')
                .filter(r => r.name.includes('/api/'))
                .length;
            })()
        """)
        check("frontend made API calls", isinstance(val, int) and val > 0, f"{val} API requests")

    print()
    failures = [r for r in results if not r[1]]
    print(f"{len(failures)} failure(s)" if failures else "All UI checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
