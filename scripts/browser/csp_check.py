"""Loads every page with the exact Content-Security-Policy from frontend/vercel.json and fails on any violation.

Part of the browser checks: run them all with `python scripts/run_browser_checks.py` (it starts a fresh fake-Supabase
server for each one). To run this one by hand, start `ALLOW_FAKE_SUPABASE=1 python scripts/dev_fake_server.py 8780`
and set BASE_URL=http://127.0.0.1:8780 (the default). Needs Playwright's Chromium (`playwright install chromium`) or
CHROME_PATH pointing at a Chrome/Chromium.
"""
import pathlib
import json, os, sys, time, urllib.request
from playwright.sync_api import sync_playwright

CHROME = os.environ.get("CHROME_PATH") or None      # None = the Chromium Playwright installed
BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8780")
cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "vercel.json"), encoding="utf-8"))
HEADERS = {h["key"]: h["value"] for h in cfg["headers"][0]["headers"]}
CSP = HEADERS["Content-Security-Policy"]
HEADERS.pop("Strict-Transport-Security")                 # meaningless over plain http
problems = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        problems.append(msg)


for _ in range(60):
    try:
        urllib.request.urlopen(BASE + "/api/health", timeout=2); break
    except Exception:
        time.sleep(1)
print("CSP under test:", CSP)

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True)
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    violations = []

    def add_headers(route):
        resp = route.fetch()
        route.fulfill(response=resp, headers={**resp.headers, **HEADERS})

    from urllib.parse import urlparse
    ctx.route(lambda url: urlparse(url).netloc == urlparse(BASE).netloc and (urlparse(url).path.endswith(".html") or urlparse(url).path == "/"), add_headers)
    page = ctx.new_page()
    page.add_init_script("window.__csp = []; document.addEventListener('securitypolicyviolation', e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));")
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "401" not in m.text else None)
    page.on("pageerror", lambda e: errors.append(str(e)))

    def violations_now():
        return page.evaluate("window.__csp || []")

    page.goto(BASE + "/login.html")
    page.wait_for_selector("#login-form")
    check(violations_now() == [], f"login page: no CSP violations {violations_now()}")
    page.fill("#email", "dev@example.com"); page.fill("#password", "dev-password-123"); page.click("#submit")
    page.wait_for_url(BASE + "/")
    page.wait_for_selector(".user-menu")
    check(violations_now() == [], f"search page: no CSP violations {violations_now()}")
    page.fill("#q", "abb"); page.wait_for_selector("#suggestions li", timeout=30000)
    check(violations_now() == [], "search suggestions: no CSP violations")

    for path, wait in (("/holdings.html", ".empty-card, table.holdings"), ("/market.html", ".m-head h1")):
        page.goto(BASE + path)
        page.wait_for_selector(wait, timeout=90000)
        page.wait_for_timeout(500)
        check(violations_now() == [], f"{path}: no CSP violations {violations_now()}")

    # the table with label pills, icons and flags (ABB was saved by the earlier run, or is saved now)
    page.goto(BASE + "/holdings.html"); page.wait_for_selector(".empty-card, table.holdings")
    if page.locator(".empty-card").count():
        page.click("#add-btn"); page.fill("#stock-input", "abb"); page.wait_for_selector("#stock-suggestions li", timeout=30000)
        page.keyboard.press("ArrowDown"); page.keyboard.press("Enter")
        page.fill("#shares", "5"); page.fill("#buy-price", "100"); page.click("#save-btn")
        page.wait_for_selector("table.holdings tbody tr", timeout=120000)
    check(violations_now() == [], f"holdings table with pills and icons: no CSP violations {violations_now()}")

    page.goto(BASE + "/report.html?symbol=ABB")
    page.wait_for_selector(".q-row", timeout=120000)
    check(violations_now() == [], f"report page: no CSP violations {violations_now()}")

    served = page.evaluate("fetch(location.href).then(r => r.headers.get('content-security-policy'))")
    check(bool(served) and "script-src 'self'" in served, "the report page really carries the policy")
    fonts_ok = page.evaluate("document.fonts.check('16px Inter')")
    check(fonts_ok, "the Inter web font loads under the policy")
    check(not errors, f"no console errors: {errors}")

    # the policy really blocks what it should
    inline = page.evaluate("""() => { try { const s = document.createElement('script'); s.textContent = 'window.__x = 1'; document.head.append(s); } catch (e) {} return window.__x === 1; }""")
    check(inline is False, "an injected inline script is blocked")
    page.evaluate("window.__csp = []; const f = document.createElement('iframe'); f.src = 'https://example.com'; document.body.append(f);")
    page.wait_for_timeout(1500)
    got = violations_now()
    check(any("frame-src" in v or "default-src" in v for v in got), f"an outside frame is blocked by the policy {got}")
    b.close()

print("\nRESULT:", "all checks passed" if not problems else f"{len(problems)} failed: {problems}")

sys.exit(1 if problems else 0)
