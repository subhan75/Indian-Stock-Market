"""Keyboard-only use, skip link, visible focus, Back navigation from every entry point, focus and announcements, form errors, phone card semantics.

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

FOCUS_INFO = """() => {
  const e = document.activeElement; if (!e || e === document.body) return null;
  const cs = getComputedStyle(e), r = e.getBoundingClientRect();
  const outlined = (parseFloat(cs.outlineWidth) > 0 && cs.outlineStyle !== 'none') || (cs.boxShadow && cs.boxShadow !== 'none');
  return { tag: e.tagName.toLowerCase(), id: e.id, text: (e.getAttribute('aria-label') || e.textContent || e.value || '').trim().slice(0, 28), outlined, visible: r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight };
}"""


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        problems.append(msg)


def tab_through(page, limit=120):
    """Press Tab until focus returns to the first stop. Returns the stops in order."""
    page.evaluate("document.activeElement && document.activeElement.blur()")
    stops = []
    for _ in range(limit):
        page.keyboard.press("Tab")
        info = page.evaluate(FOCUS_INFO)
        if info is None:
            break
        key = (info["tag"], info["id"], info["text"])
        if stops and key == (stops[0]["tag"], stops[0]["id"], stops[0]["text"]):
            break
        stops.append(info)
    return stops


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
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "401" not in m.text else None)

    # ---------------- keyboard only: sign in without a mouse
    page.goto(BASE + "/login.html")
    page.wait_for_selector("#login-form")
    page.keyboard.press("Tab")
    info = page.evaluate(FOCUS_INFO)
    check(info["tag"] == "a" and "Skip" in info["text"] and info["visible"], f"login: the first Tab stop is the visible skip link ({info})")
    page.keyboard.press("Enter")
    check(page.evaluate("document.activeElement.id") == "main", "login: Enter on the skip link moves focus to the main content")
    page.keyboard.press("Tab")
    check(page.evaluate("document.activeElement.id") == "email", "login: next Tab lands in the email field")
    page.keyboard.type(EMAIL)
    page.keyboard.press("Tab"); page.keyboard.type(PASSWORD)
    page.keyboard.press("Tab")
    check(page.evaluate("document.activeElement.id") == "toggle-password", "login: Tab reaches Show password")
    page.keyboard.press("Tab"); page.keyboard.press("Enter")
    page.wait_for_url(BASE + "/")
    check(True, "login: signed in with the keyboard alone")

    # ---------------- every page: skip link first, visible focus everywhere, no trap
    for name, path, ready in (("search", "/", "#recent-list li"), ("report", "/report.html?symbol=ABB", ".q-row"),
                              ("holdings", "/holdings.html", "table.holdings tbody tr"), ("market", "/market.html", ".index-card")):
        page.goto(BASE + path)
        page.wait_for_selector(ready, timeout=120000)
        stops = tab_through(page)
        check(len(stops) > 3 and "Skip" in stops[0]["text"], f"{name}: the skip link is the first stop of {len(stops)}")
        unseen = [s for s in stops if not s["outlined"]]
        check(not unseen, f"{name}: every keyboard stop has a visible focus ring {[s['text'] for s in unseen][:3]}")
        offscreen = [s for s in stops if not s["visible"]]
        check(not offscreen or all(s["tag"] in ("a", "button") and "Skip" in s["text"] for s in offscreen), f"{name}: no stop is hidden off screen {[s['text'] for s in offscreen][:3]}")
        check(len(stops) < 120, f"{name}: Tab cycles back to the start, so there is no keyboard trap")
        page.keyboard.press("Tab"); page.keyboard.press("Enter")
        check(page.evaluate("document.activeElement.id") == "main", f"{name}: the skip link moves focus to the main content")
        check(page.locator("main[aria-live]").count() == 0, f"{name}: <main> is not a live region (it would be read out in full on every change)")
        check(page.locator("main#main").count() == 1 and page.locator("h1").count() >= 1, f"{name}: one main landmark and at least one h1")

    # ---------------- a finished load is announced, without taking focus away from the top of the page
    for name, path, ready, expect in (("report", "/report.html?symbol=ABB", ".q-row", "report is ready"), ("holdings", "/holdings.html", "table.holdings", "Your stocks are ready"), ("market", "/market.html", ".index-card", "Market today is ready")):
        page.goto(BASE + path); page.wait_for_selector(ready, timeout=120000); page.wait_for_timeout(500)
        said = page.inner_text("#announcer")
        check(expect in said, f"{name}: a status message says the page is ready ({said!r})")
        check(page.get_attribute("#announcer", "role") == "status" and page.get_attribute("#announcer", "aria-live") == "polite", f"{name}: it is a polite live region")
        check(page.evaluate("document.activeElement.tagName") == "BODY", f"{name}: focus was not stolen from the top of the page")

    # ---------------- an in-page refresh does move focus to the heading (the Refresh button disappears)
    page.goto(BASE + "/market.html"); page.wait_for_selector(".index-card", timeout=90000)
    page.click(".m-head button"); page.wait_for_selector(".skeleton"); page.wait_for_selector(".index-card", timeout=90000)
    page.wait_for_timeout(300)
    check(page.evaluate("document.activeElement.tagName") == "H1", "after clicking Refresh, focus lands on the page heading")

    # ---------------- going back: from My stocks
    page.goto(BASE + "/holdings.html"); page.wait_for_selector("table.holdings tbody tr")
    page.locator("a.name", has_text="ABB").first.click()
    page.wait_for_selector(".q-row", timeout=120000)
    check("from=holdings" in page.url, "report opened from My stocks knows where it came from")
    back = page.locator(".back-link")
    check((await_text := back.inner_text().strip()).endswith("Back to My stocks"), f"the Back link says where it goes: {await_text!r}")
    check(page.locator(".nav a[aria-current='page']").inner_text().strip() == "My stocks", "the menu highlights My stocks, not Search")
    back.click()
    page.wait_for_url("**/holdings.html")
    page.wait_for_selector("table.holdings tbody tr")
    check(True, "Back returns to My stocks")

    # ---------------- going back: from Market today
    page.goto(BASE + "/market.html"); page.wait_for_selector(".index-card", timeout=90000)
    link = page.locator(".stock-row .name a").first
    if link.count():
        link.click(); page.wait_for_selector(".q-row", timeout=120000)
        check("Back to Market today" in page.inner_text(".back-link"), "a report opened from Market today goes back to Market today")
        page.click(".back-link"); page.wait_for_url("**/market.html")
        check(True, "Back returns to Market today")

    # ---------------- going back: search text survives
    page.goto(BASE + "/"); page.wait_for_selector("#recent-list li")
    page.fill("#q", "abb"); page.wait_for_selector("#suggestions li", timeout=30000)
    check("q=abb" in page.url, f"what you type is kept in the address: {page.url}")
    page.keyboard.press("ArrowDown"); page.keyboard.press("Enter")
    page.wait_for_selector(".q-row", timeout=120000)
    check("Back to Search" in page.inner_text(".back-link"), "a report opened from Search says Back to Search")
    page.go_back()
    page.wait_for_url("**/?q=abb")
    page.wait_for_selector("#suggestions li", timeout=30000)
    check(page.input_value("#q") == "abb", "the browser's Back button brings back the search text")
    check(page.locator("#suggestions li").count() > 0, "…and the suggestions")
    page.goto(BASE + "/"); page.fill("#q", "abb"); page.wait_for_selector("#suggestions li", timeout=30000)
    page.keyboard.press("ArrowDown"); page.keyboard.press("Enter"); page.wait_for_selector(".q-row", timeout=120000)
    page.click(".back-link")
    page.wait_for_url("**/?q=abb")
    check(page.input_value("#q") == "abb", "the on-page Back link restores the search too")

    # a report opened directly has a sensible Back link
    page.goto(BASE + "/report.html?symbol=ABB"); page.wait_for_selector(".q-row", timeout=120000)
    check("Back to Search" in page.inner_text(".back-link"), "a report opened directly offers Back to Search")
    # bfcache friendliness: no unload handlers
    check(page.evaluate("typeof window.onunload") == "object" and page.evaluate("window.onunload === null"), "no unload handler (pages stay eligible for instant Back)")

    # ---------------- external links say they open a new tab
    ext = page.eval_on_selector_all("main a[target='_blank']", "els => els.map(a => ({ label: a.getAttribute('aria-label') || '', hidden: a.querySelector('.sr-only') ? a.querySelector('.sr-only').textContent : '' }))")
    check(ext and all("new tab" in (e['label'] + e['hidden']) for e in ext), f"all {len(ext)} external links announce that they open in a new tab")

    # ---------------- form errors name the field
    page.goto(BASE + "/holdings.html"); page.wait_for_selector("table.holdings tbody tr")
    page.click("#add-btn"); page.wait_for_selector("#stock-dialog[open]")
    page.click("#save-btn")
    check(page.get_attribute("#stock-input", "aria-invalid") == "true" and page.evaluate("document.activeElement.id") == "stock-input", "no stock chosen: the stock field is marked invalid and focused")
    check(page.get_attribute("#stock-input", "aria-describedby") == "form-error" and page.get_attribute("#form-error", "role") == "alert", "the error is announced and tied to that field")
    page.fill("#stock-input", "abb"); page.wait_for_selector("#stock-suggestions li", timeout=30000)
    page.keyboard.press("ArrowDown"); page.keyboard.press("Enter")
    page.fill("#shares", "0"); page.click("#save-btn")
    check(page.get_attribute("#shares", "aria-invalid") == "true" and page.get_attribute("#stock-input", "aria-invalid") == "false", "shares problem: only the shares field is marked invalid")
    page.fill("#shares", "5"); page.fill("#buy-price", ""); page.click("#save-btn")
    check(page.get_attribute("#buy-price", "aria-invalid") == "true", "price problem: only the price field is marked invalid")
    page.keyboard.press("Escape")
    check(page.evaluate("document.activeElement.id") == "add-btn", "closing the dialog returns focus to the button that opened it")

    # ---------------- the phone card layout keeps its meaning for screen readers
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(BASE + "/holdings.html"); page.wait_for_selector("table.holdings tbody tr")
    labels = page.eval_on_selector_all("table.holdings tbody tr:first-child .cell-label", "els => els.filter(e => getComputedStyle(e).display !== 'none').map(e => e.textContent)")
    check("Shares and buy price" in labels and "Value today" in labels and "Look at this" in labels, f"phone card: every value has a real label element {labels}")
    snap = page.locator("table.holdings").aria_snapshot()
    check("Shares and buy price" in snap and "table" in snap and "row" in snap, "phone card: the table, rows and labelled cells are still in the accessibility tree")
    print(snap[:700])
    page.set_viewport_size({"width": 1280, "height": 900})
    page.reload(); page.wait_for_selector("table.holdings tbody tr")
    hidden = page.eval_on_selector_all("table.holdings .cell-label", "els => els.every(e => getComputedStyle(e).display === 'none')")
    check(hidden, "desktop: the labels are hidden (the column headings do that job), so nothing is read twice")
    check(page.locator("table.holdings th[role='columnheader']").count() == 7, "desktop: the column headings are real column headers")

    print("\nBROWSER ERRORS:", errors or "none")
    browser.close()

print("\nRESULT:", "all checks passed" if not problems else f"{len(problems)} failed")
for m in problems: print(" -", m[:240])

sys.exit(1 if problems else 0)
