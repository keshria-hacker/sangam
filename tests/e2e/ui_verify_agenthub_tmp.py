"""One-off UI verification (temp DB) — proves the new Agent Hub options and
Create Hub 8th template are visible in the real UI. Run with the app on
127.0.0.1:5500 (frontend) / 127.0.0.1:8001 (backend, temp DATABASE_URL).
"""
import glob
import os
import sys

from playwright.sync_api import sync_playwright

FRONTEND = "http://127.0.0.1:5500"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
os.makedirs(OUT, exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}: {name} {detail}", flush=True)


def launch(pw):
    try:
        return pw.chromium.launch(headless=True)
    except Exception:
        candidates = sorted(
            glob.glob(os.path.expandvars(
                r"%LOCALAPPDATA%\ms-playwright\chromium-*\chrome-win\chrome.exe")),
            reverse=True)
        if candidates:
            return pw.chromium.launch(headless=True, executable_path=candidates[0])
        raise


def open_tool(page, tool):
    """Open a studio tool via the tab picker; deep-link fallback via module."""
    picker = page.locator("#tabAdd")
    if picker.count():
        picker.click()
        page.wait_for_timeout(300)
        btn = page.locator(f"[data-tab-tool='{tool}']")
        if btn.count():
            btn.click()
            page.wait_for_timeout(2000)
            return True
    # Fallback: call the tab module directly
    page.evaluate(
        f"import('/js/features/tabs/tabs.js').then(m => m.openToolTab('{tool}'))")
    page.wait_for_timeout(2500)
    return True


def main():
    with sync_playwright() as pw:
        browser = launch(pw)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(FRONTEND)
        page.wait_for_selector("#messages", timeout=20000)

        # Register a throwaway user on the temp DB
        page.wait_for_timeout(2500)
        try:
            page.wait_for_selector("#authForm:not(.hidden)", timeout=8000)
        except Exception:
            pass
        if page.locator("#authForm:not(.hidden)").count():
            page.fill("#authUsername", "ui_verify")
            page.fill("#authPassword", "UiVerifyPass1")
            confirm = page.locator("#authConfirmPassword")
            if confirm.count() and confirm.is_visible():
                confirm.fill("UiVerifyPass1")
            page.click("#authSubmit")
        try:
            page.wait_for_function(
                "() => (document.querySelector('#authOverlay')||{}).classList?.contains('hidden')",
                timeout=20000)
            check("auth completed", True)
        except Exception:
            check("auth completed", False,
                  page.locator("#authOverlay").get_attribute("class") or "no-overlay")
        page.wait_for_timeout(1500)
        page.screenshot(path=os.path.join(OUT, "01-after-auth.png"))

        # --- Agent Hub: approval policy + cost budget ---
        open_tool(page, "agents")
        btn = page.locator("#hubNew")
        check("agent hub 'New agent' visible", btn.count() > 0 and btn.is_visible())
        if btn.count():
            btn.click()
            try:
                page.wait_for_selector("select[name='approval_policy']", timeout=10000)
            except Exception:
                pass
            sel = page.locator("select[name='approval_policy']")
            bud = page.locator("input[name='cost_budget']")
            check("approval policy select visible", sel.count() > 0 and sel.is_visible())
            if sel.count():
                opts = sel.locator("option").all_inner_texts()
                check("policy has 3 options", len(opts) == 3, str(opts))
            check("cost budget input visible", bud.count() > 0 and bud.is_visible())
            page.screenshot(path=os.path.join(OUT, "02-agent-form-policy-budget.png"))

            if sel.count() and bud.count():
                page.fill("input[name='name']", "Test Agent")
                sel.select_option("always_ask")
                bud.fill("0.5")
                page.click("#hubForm button[type='submit']")
                page.wait_for_timeout(1500)
                card_hint = page.locator(".hub-card .settings-hint").last.inner_text()
                check("card shows policy+budget",
                      "always_ask" in card_hint and "0.50" in card_hint, card_hint)
                page.screenshot(path=os.path.join(OUT, "03-agent-card-policy.png"))

        # --- Create Hub: 8 templates incl. Spec doc ---
        open_tool(page, "create")
        # templates live in the documents sub-view; find the grid wherever it is
        page.wait_for_timeout(1000)
        grid = page.locator("#createTemplates")
        check("create templates grid", grid.count() > 0 and grid.is_visible())
        tpl_count = grid.locator("label, button, .hub-card").count()
        spec = page.locator("#createTemplates", has_text="Spec doc").count()
        check("8 starter templates", tpl_count >= 8, f"count={tpl_count}")
        check("Spec doc template present", spec > 0)
        page.screenshot(path=os.path.join(OUT, "04-create-hub-8-templates.png"))

        browser.close()

    fails = [r for r in results if not r[1]]
    print(f"\nSUMMARY: {len(results) - len(fails)}/{len(results)} checks passed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
