"""Sign-in, the guard on every page, Log out, the return-to-page redirect, open-redirect protection and cookies.

Part of the browser checks: run them all with `python scripts/run_browser_checks.py` (it starts a fresh fake-Supabase
server for each one). To run this one by hand, start `ALLOW_FAKE_SUPABASE=1 python scripts/dev_fake_server.py 8780`
and set BASE_URL=http://127.0.0.1:8780 (the default). Needs Playwright's Chromium (`playwright install chromium`) or
CHROME_PATH pointing at a Chrome/Chromium.
"""
import pathlib
import os, sys, time, urllib.request
from playwright.sync_api import sync_playwright

OUT = sys.argv[1] if len(sys.argv) > 1 else str(pathlib.Path(__file__).resolve().parent / "output")
os.makedirs(OUT, exist_ok=True)
CHROME = os.environ.get("CHROME_PATH") or None      # None = the Chromium Playwright installed
BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8780")
EMAIL, PASSWORD = "dev@example.com", "dev-password-123"
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

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=CHROME, headless=True)
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)

    # ---- signed out: every page sends you to the login page and remembers where you were going
    for path in ("/holdings.html", "/market.html", "/report.html?symbol=ABB", "/"):
        page.goto(BASE + path)
        page.wait_for_url("**/login.html**", timeout=20000)
        check("next=" in page.url, f"{path} while signed out goes to login with a return address")
    page.goto(BASE + "/holdings.html")
    page.wait_for_url("**/login.html?next=**")
    check(page.inner_text("h1") == "Sign in", "the login page has an h1 'Sign in'")
    check(page.title() == "Sign in | Stock Analyst", "the login page title")
    page.screenshot(path=f"{OUT}/login_empty.png")

    # ---- validation and wrong password
    page.click("#submit")
    check(page.inner_text("#form-error") == "Enter your email and password.", "empty form shows the plain message")
    check(page.evaluate("document.activeElement.id") == "email", "focus goes to the empty field")
    page.fill("#email", EMAIL)
    page.click("#submit")
    check(page.evaluate("document.activeElement.id") == "password" and page.get_attribute("#password", "aria-invalid") == "true",
          "missing password: focus and aria-invalid on the password field")
    page.fill("#password", "wrong-password")
    page.click("#submit")
    page.wait_for_function("document.getElementById('form-error').textContent.includes('Wrong email or password.')")
    check(True, "wrong password shows 'Wrong email or password.'")
    check(page.input_value("#password") == "", "the password field is cleared after a failure")
    check(page.get_attribute("#password", "aria-describedby") == "form-error", "the error is tied to the field for screen readers")
    page.screenshot(path=f"{OUT}/login_error.png")

    # ---- show / hide password
    page.fill("#password", "abc")
    check(page.get_attribute("#password", "type") == "password", "password hidden by default")
    page.click("#toggle-password")
    check(page.get_attribute("#password", "type") == "text" and page.get_attribute("#toggle-password", "aria-pressed") == "true", "Show reveals the password")
    page.click("#toggle-password")
    check(page.get_attribute("#password", "type") == "password", "Hide hides it again")

    # ---- success returns you to where you were going
    page.fill("#email", EMAIL)
    page.fill("#password", PASSWORD)
    page.click("#submit")
    page.wait_for_url("**/holdings.html", timeout=30000)
    check(page.url.endswith("/holdings.html"), "after signing in you land back on /holdings.html")
    page.wait_for_selector(".user-menu")
    check(EMAIL in page.inner_text(".user-menu") and "Log out" in page.inner_text(".user-menu"), "header shows who is signed in and Log out")
    cookies = {c["name"]: c for c in ctx.cookies()}
    check({"sb-access", "sb-refresh"} <= set(cookies), "session cookies exist")
    check(all(c["httpOnly"] for c in cookies.values()), "the cookies are HttpOnly")
    check(page.evaluate("document.cookie") == "", "page JavaScript cannot see any cookie")
    check(page.evaluate("JSON.stringify(localStorage) + JSON.stringify(sessionStorage)") == "{}{}", "no token is stored in browser storage")
    page.wait_for_selector(".empty-card")
    page.screenshot(path=f"{OUT}/signed_in_holdings.png")

    # ---- the login page skips the form when already signed in
    page.goto(BASE + "/login.html?next=/market.html")
    page.wait_for_url("**/market.html", timeout=20000)
    check(True, "visiting login while signed in goes straight to the page you asked for")

    # ---- open-redirect protection
    page.goto(BASE + "/login.html?next=https://evil.example/steal")
    page.wait_for_url(BASE + "/", timeout=20000)
    check(page.url == BASE + "/", "an outside 'next' address is ignored")
    page.goto(BASE + "/login.html?next=//evil.example")
    page.wait_for_url(BASE + "/", timeout=20000)
    check(page.url == BASE + "/", "a '//' 'next' address is ignored")

    # ---- log out
    page.click(".user-menu .link-btn-sm")
    page.wait_for_url("**/login.html", timeout=20000)
    check(page.url.endswith("/login.html"), "Log out goes to the login page")
    page.goto(BASE + "/holdings.html")
    page.wait_for_url("**/login.html**")
    check(True, "after logging out, protected pages ask for sign-in again")

    # ---- two accounts keep separate lists
    page.goto(BASE + "/login.html?next=/holdings.html")
    page.fill("#email", EMAIL); page.fill("#password", PASSWORD); page.click("#submit")
    page.wait_for_url("**/holdings.html")
    page.wait_for_selector(".empty-card")
    page.click("#add-btn")
    page.fill("#stock-input", "titan")
    page.wait_for_selector("#stock-suggestions li", timeout=30000)
    page.keyboard.press("ArrowDown"); page.keyboard.press("Enter")
    page.check("#watching"); page.click("#save-btn")
    page.wait_for_selector("table.holdings tbody tr", timeout=120000)
    check("Titan" in page.inner_text("table.holdings"), "account one saved a stock")
    page.click(".user-menu .link-btn-sm"); page.wait_for_url("**/login.html")
    page.fill("#email", "partner@example.com"); page.fill("#password", "partner-password-123"); page.click("#submit")
    page.wait_for_url(BASE + "/")
    page.goto(BASE + "/holdings.html")
    page.wait_for_selector(".empty-card", timeout=30000)
    check(True, "account two sees none of account one's stocks")

    # ---- mobile layout of the login page
    m = browser.new_page(viewport={"width": 375, "height": 740}, device_scale_factor=2)
    m.goto(BASE + "/login.html")
    m.wait_for_selector("#login-form")
    check(m.evaluate("document.documentElement.scrollWidth") <= 375, "no sideways scroll on the login page at 375px")
    sizes = m.evaluate("[...document.querySelectorAll('#login-form input, #login-form button')].map(e => [e.id, e.getBoundingClientRect().height, parseFloat(getComputedStyle(e).fontSize)])")
    check(all(h >= 44 for _, h, _ in sizes), f"touch targets at least 44px: {sizes}")
    check(all(fs >= 16 for _, _, fs in sizes if _ in ("email", "password")), "inputs are 16px or larger (no iPhone zoom)")
    m.screenshot(path=f"{OUT}/login_mobile.png")

    print("\nBROWSER ERRORS:", [e for e in errors if "401" not in e] or "none")
    browser.close()

print("\nRESULT:", "all checks passed" if not problems else f"{len(problems)} failed: {problems}")

sys.exit(1 if problems else 0)
