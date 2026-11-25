"""A loader appears for every slow operation (against deliberately delayed responses), plus offline and reduced motion.

Part of the browser checks: run them all with `python scripts/run_browser_checks.py` (it starts a fresh fake-Supabase
server for each one). To run this one by hand, start `ALLOW_FAKE_SUPABASE=1 python scripts/dev_fake_server.py 8780`
and set BASE_URL=http://127.0.0.1:8780 (the default). Needs Playwright's Chromium (`playwright install chromium`) or
CHROME_PATH pointing at a Chrome/Chromium.
"""
import pathlib
import asyncio, os, sys, time, urllib.request
from playwright.async_api import async_playwright

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


def delayed(page, pattern, seconds):
    async def handler(route):
        await asyncio.sleep(seconds)
        await route.continue_()
    return page.route(pattern, handler)


async def main():
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/api/health", timeout=2); break
        except Exception:
            time.sleep(1)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=CHROME, headless=True)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "401" not in m.text else None)

        # ---------------- login button
        await page.goto(BASE + "/login.html")
        await delayed(page, "**/api/auth/login", 1.5)
        await page.fill("#email", EMAIL); await page.fill("#password", "wrong-password")
        await page.click("#submit")
        await page.wait_for_selector("#submit[aria-busy='true']", timeout=2000)
        txt = (await page.inner_text("#submit")).strip()
        check(txt == "Signing in…" and await page.locator("#submit .spinner").count() == 1, f"login button shows a spinner and '{txt}'")
        check(await page.is_disabled("#submit"), "login button is disabled while working")
        await page.wait_for_selector("#form-error:not([hidden])", timeout=5000)
        check((await page.inner_text("#submit")).strip() == "Sign in" and not await page.is_disabled("#submit"), "button is restored after a failure")
        await page.unroute("**/api/auth/login")
        await page.fill("#password", PASSWORD); await page.click("#submit")
        await page.wait_for_url(BASE + "/")

        # ---------------- search page: recent list + suggestions spinner + Research button
        await page.goto(BASE + "/login.html")      # signed in -> back to home
        await page.wait_for_url(BASE + "/")
        await delayed(page, "**/api/reports/recent*", 1.5)
        await page.reload()
        await page.wait_for_selector("#recent-list .loading-note", timeout=3000)
        note = page.locator("#recent-list .loading-note")
        check(await note.get_attribute("role") == "status" and "Loading your stocks" in await note.inner_text(), "the recent list shows 'Loading your stocks…'")
        check(await note.locator(".spinner").count() == 1, "…with a spinner icon")
        await page.wait_for_selector("#recent-list .loading-note", state="detached", timeout=6000)
        check(await page.locator("#recent-list .loading-note").count() == 0, "the loading note is gone once loaded")
        await page.unroute("**/api/reports/recent*")

        await delayed(page, "**/api/stocks/search*", 1.5)
        await page.fill("#q", "abb")
        await page.wait_for_selector(".combo-spinner:not([hidden])", timeout=3000)
        check((await page.inner_text("#hint")).strip() == "Searching…", "search shows a spinner in the box and 'Searching…' (announced)")
        await page.wait_for_selector("#suggestions li", timeout=6000)
        check(await page.locator(".combo-spinner").is_hidden(), "the spinner hides when suggestions arrive")
        await page.unroute("**/api/stocks/search*")

        # ---------------- report page with a slow report (also the 8 s "taking longer" message)
        await delayed(page, "**/api/reports/ABB*", 10)
        await page.goto(BASE + "/report.html?symbol=ABB")
        await page.wait_for_selector(".loading-note", timeout=3000)
        check((await page.inner_text("h1")).strip() == "Report for ABB", "the report page has an h1 while loading")
        check(await page.locator(".loading-note[role='status'] .spinner").count() == 1, "report loading shows a spinner in a status region")
        first = (await page.inner_text(".loading-text")).strip()
        check("up to a minute" in first, f"first message sets expectations: {first!r}")
        await page.wait_for_function("document.querySelector('.loading-text').textContent.includes('longer than usual')", timeout=12000)
        check(True, "after 8 s it says 'This is taking longer than usual. Still working…'")
        elapsed = (await page.inner_text(".loading-elapsed")).strip()
        check(elapsed.endswith(" s") and await page.locator(".loading-elapsed[aria-hidden='true']").count() == 1, f"a visual seconds counter ({elapsed}) that screen readers are not told every second")
        await page.screenshot(path=f"{OUT}/loader_report_slow.png")
        await page.wait_for_selector(".q-row", timeout=120000)
        check(await page.locator(".loading-note").count() == 0, "the loader disappears when the report is shown")
        await page.unroute("**/api/reports/ABB*")

        # ---------------- my stocks: load, save, refresh all progress
        await delayed(page, "**/api/holdings", 1.5)
        await page.goto(BASE + "/holdings.html")
        await page.wait_for_selector(".loading-note", timeout=3000)
        check("Loading your stocks" in await page.inner_text(".loading-note"), "My stocks shows 'Loading your stocks…' while loading")
        await page.wait_for_selector(".empty-card, table.holdings", timeout=8000)
        await page.unroute("**/api/holdings")

        await page.wait_for_selector("#add-btn")
        if await page.locator(".empty-card").count():
            await page.click("#add-btn")
            await page.fill("#stock-input", "abb")
            await page.wait_for_selector("#stock-suggestions li", timeout=30000)
            await page.keyboard.press("ArrowDown"); await page.keyboard.press("Enter")
            await page.fill("#shares", "5"); await page.fill("#buy-price", "100")
            await page.click("#save-btn")
            await page.wait_for_selector("#save-btn[aria-busy='true']", timeout=2000)
            check((await page.inner_text("#save-btn")).strip() == "Saving…" and await page.locator("#save-btn .spinner").count() == 1, "Save shows a spinner and 'Saving…'")
            await page.wait_for_selector("table.holdings tbody tr", timeout=120000)
            check((await page.inner_text("#status")).startswith("Saved"), "save completes")

        await page.click("#refresh-btn")
        await page.wait_for_selector("#refresh-btn[aria-busy='true']", timeout=2000)
        status = (await page.inner_text("#status")).strip()
        check(status.startswith("Refreshing 1 of ") and " of " in status, f"Refresh all shows live progress: {status!r}")
        check(await page.locator("#status .spinner").count() == 1, "…with a spinner")
        check(await page.is_disabled("#add-btn"), "other buttons are disabled meanwhile")
        await page.wait_for_function("document.getElementById('status').innerText.includes('Refreshed')", timeout=240000)
        check(not await page.is_disabled("#refresh-btn") and (await page.inner_text("#refresh-btn")).strip() == "Refresh all", "Refresh all is restored afterwards")

        # remove shows progress
        await delayed(page, "**/api/holdings/*", 1.2)
        await page.click("button[aria-label^='Remove ']")
        await page.wait_for_selector("#confirm-dialog[open]")
        await page.click("#confirm-yes")
        await page.wait_for_selector("#status .status-busy", timeout=3000)
        check("Removing" in await page.inner_text("#status"), "Remove shows 'Removing …' with a spinner")
        await page.wait_for_function("document.getElementById('status').innerText.startsWith('Removed')", timeout=10000)
        await page.unroute("**/api/holdings/*")

        # ---------------- market
        await delayed(page, "**/api/market/today*", 1.5)
        await page.goto(BASE + "/market.html")
        await page.wait_for_selector(".loading-note", timeout=3000)
        check((await page.inner_text("h1")).strip() == "Market today" and "Getting today" in await page.inner_text(".loading-note"), "Market today shows a heading and 'Getting today's market…'")
        await page.wait_for_selector(".index-card", timeout=90000)
        await page.unroute("**/api/market/today*")

        # ---------------- logout button
        await delayed(page, "**/api/auth/logout", 1.2)
        await page.click(".user-menu .link-btn-sm")
        await page.wait_for_selector(".user-menu button[aria-busy='true']", timeout=2000)
        check("Logging out" in await page.inner_text(".user-menu"), "Log out shows 'Logging out…' with a spinner")
        await page.wait_for_url("**/login.html", timeout=8000)

        # ---------------- offline banner and message
        await page.goto(BASE + "/login.html")
        await page.fill("#email", EMAIL); await page.fill("#password", PASSWORD); await page.click("#submit")
        await page.wait_for_url(BASE + "/")
        await page.wait_for_selector(".user-menu")
        check(await page.locator(".offline-banner").is_hidden(), "no offline banner while online")
        await ctx.set_offline(True)
        await page.wait_for_selector(".offline-banner:not([hidden])", timeout=3000)
        check("offline" in (await page.inner_text(".offline-banner")).lower() and await page.get_attribute(".offline-banner", "role") == "status", "going offline shows a banner (announced as status)")
        await page.fill("#q", "ab")
        await page.wait_for_function("document.getElementById('hint').textContent.length > 0 && !document.getElementById('hint').textContent.includes('Searching')", timeout=5000)
        check("offline" in (await page.inner_text("#hint")).lower(), f"a search while offline says so: {(await page.inner_text('#hint'))!r}")
        await ctx.set_offline(False)
        await page.wait_for_selector(".offline-banner", state="hidden", timeout=3000)
        check(True, "the banner goes away when the connection returns")

        # ---------------- reduced motion: no spinning, but the words stay
        await page.emulate_media(reduced_motion="reduce")
        await delayed(page, "**/api/market/today*", 1.5)
        await page.goto(BASE + "/market.html")
        await page.wait_for_selector(".loading-note .spinner-arc", state="attached", timeout=3000)
        anim = await page.evaluate("getComputedStyle(document.querySelector('.spinner-arc')).animationName")
        check(anim == "none", f"with reduced motion the spinner does not animate (animation-name: {anim})")
        check("Getting today" in await page.inner_text(".loading-note"), "…but the words remain")
        await page.wait_for_selector(".index-card", timeout=90000)

        print("\nBROWSER ERRORS:", errors or "none")
        await browser.close()
    print("\nRESULT:", "all checks passed" if not problems else f"{len(problems)} failed: {problems}")


asyncio.run(main())

sys.exit(1 if problems else 0)
