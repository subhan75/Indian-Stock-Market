"""Runs the axe-core accessibility scanner on every page and state, at desktop and phone size. Fails on serious or critical findings.

Part of the browser checks: run them all with `python scripts/run_browser_checks.py` (it starts a fresh fake-Supabase
server for each one). To run this one by hand, start `ALLOW_FAKE_SUPABASE=1 python scripts/dev_fake_server.py 8780`
and set BASE_URL=http://127.0.0.1:8780 (the default). Needs Playwright's Chromium (`playwright install chromium`) or
CHROME_PATH pointing at a Chrome/Chromium.
"""
import pathlib
import json, os, sys, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

CHROME = os.environ.get("CHROME_PATH") or None      # None = the Chromium Playwright installed
import axe_playwright_python
AXE = (Path(axe_playwright_python.__file__).parent / "axe.min.js").read_text(encoding="utf-8")
BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8780")
EMAIL, PASSWORD = "dev@example.com", "dev-password-123"
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]

summary = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}
blocking = []


def scan(page, label):
    page.evaluate(AXE) if not page.evaluate("typeof axe !== 'undefined'") else None
    result = page.evaluate("(tags) => axe.run(document, { runOnly: { type: 'tag', values: tags } })", TAGS)
    found = result["violations"]
    print(f"== {label}: {len(found)} violation type(s), {len(result['passes'])} rules passed")
    for v in found:
        impact = v["impact"] or "minor"
        summary[impact] += len(v["nodes"])
        if impact in ("critical", "serious"):
            blocking.append((label, v["id"]))
        print(f"   [{impact}] {v['id']}: {v['help']} ({len(v['nodes'])} element(s))")
        for n in v["nodes"][:2]:
            print("        ", n["target"][0][:90], "|", (n.get("failureSummary") or "").split("\n")[1][:110] if n.get("failureSummary") else "")


for _ in range(60):
    try:
        urllib.request.urlopen(BASE + "/api/health", timeout=2); break
    except Exception:
        time.sleep(1)

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME, headless=True)
    for size_name, vp, mobile in (("desktop", {"width": 1280, "height": 900}, False), ("phone", {"width": 390, "height": 800}, True)):
        ctx = browser.new_context(viewport=vp, device_scale_factor=1, is_mobile=mobile, has_touch=mobile)
        page = ctx.new_page()
        page.goto(BASE + "/login.html"); page.wait_for_selector("#login-form")
        scan(page, f"{size_name} login")
        page.fill("#email", EMAIL); page.fill("#password", "wrong"); page.click("#submit")
        page.wait_for_selector("#form-error:not([hidden])")
        scan(page, f"{size_name} login with an error")
        page.fill("#email", EMAIL); page.fill("#password", PASSWORD); page.click("#submit")
        page.wait_for_url(BASE + "/"); page.wait_for_selector(".user-menu"); page.wait_for_selector("#recent-list li")
        scan(page, f"{size_name} search page")
        page.fill("#q", "abb"); page.wait_for_selector("#suggestions li", timeout=30000)
        scan(page, f"{size_name} search with suggestions")
        page.goto(BASE + "/report.html?symbol=ABB"); page.wait_for_selector(".q-row", timeout=120000)
        page.locator("details summary").click()
        scan(page, f"{size_name} report")
        page.goto(BASE + "/holdings.html"); page.wait_for_selector("table.holdings tbody tr, .empty-card", timeout=60000)
        scan(page, f"{size_name} my stocks")
        page.click("#add-btn"); page.wait_for_selector("#stock-dialog[open]")
        scan(page, f"{size_name} add dialog")
        page.click("#save-btn")
        scan(page, f"{size_name} add dialog with an error")
        page.keyboard.press("Escape")
        page.goto(BASE + "/market.html"); page.wait_for_selector(".index-card", timeout=90000)
        scan(page, f"{size_name} market today")
        ctx.close()
    browser.close()

print("\nTOTAL elements by impact:", summary)
print("BLOCKING (serious or critical):", sorted(set(blocking)) or "none")

sys.exit(1 if blocking else 0)
