"""Phone layout at 320, 375, 390, 412 and 768 px: no sideways scroll, 16 px inputs, 44 px tap targets, bottom tab bar, bottom-sheet dialogs.

Part of the browser checks: run them all with `python scripts/run_browser_checks.py` (it starts a fresh fake-Supabase
server for each one). To run this one by hand, start `ALLOW_FAKE_SUPABASE=1 python scripts/dev_fake_server.py 8780`
and set BASE_URL=http://127.0.0.1:8780 (the default). Needs Playwright's Chromium (`playwright install chromium`) or
CHROME_PATH pointing at a Chrome/Chromium.
"""
import pathlib
import json, os, sys, time, urllib.request
from playwright.sync_api import sync_playwright

OUT = sys.argv[1] if len(sys.argv) > 1 else str(pathlib.Path(__file__).resolve().parent / "output")
os.makedirs(OUT, exist_ok=True)
CHROME = os.environ.get("CHROME_PATH") or None      # None = the Chromium Playwright installed
BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8780")
EMAIL, PASSWORD = "dev@example.com", "dev-password-123"
WIDTHS = [320, 375, 390, 412, 768]
problems = []

OVERFLOW_JS = """() => {
  const vw = document.documentElement.clientWidth, out = [];
  const scrollable = (el) => { for (let n = el.parentElement; n; n = n.parentElement) { const o = getComputedStyle(n).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return true; } return false; };
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (r.width === 0 || r.height === 0 || cs.visibility === 'hidden' || cs.display === 'none' || cs.position === 'fixed') continue;
    if (el.closest('.sr-only, [hidden], dialog:not([open])')) continue;
    if (r.right > vw + 1 && !scrollable(el)) out.push(el.tagName.toLowerCase() + '.' + (el.className || '').toString().split(' ')[0] + ' right=' + Math.round(r.right));
  }
  return { scrollWidth: document.documentElement.scrollWidth, vw, offenders: out.slice(0, 6) };
}"""

TARGETS_JS = """() => {
  const sel = "button, input:not([type=checkbox]), summary, .nav a, .recent-list a, .holdings a.name, .link-btn, .link-btn-sm, [role=option], .btn, .btn-secondary, select";
  const small = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (r.width === 0 || r.height === 0 || cs.visibility === 'hidden' || cs.display === 'none') continue;
    if (el.closest('.sr-only, [hidden], dialog:not([open])')) continue;
    if (Math.min(r.width, r.height) < 43.5) small.push((el.id || el.className || el.tagName).toString().split(' ')[0] + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
  }
  const fonts = [...document.querySelectorAll('input:not([type=checkbox]), select, textarea')]
    .filter((e) => e.offsetParent !== null && parseFloat(getComputedStyle(e).fontSize) < 16)
    .map((e) => (e.id || e.name) + ' ' + getComputedStyle(e).fontSize);
  return { small, fonts };
}"""


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
    ctx = browser.new_context(viewport={"width": 390, "height": 800}, device_scale_factor=2, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "401" not in m.text else None)

    page.goto(BASE + "/login.html")
    page.fill("#email", EMAIL); page.fill("#password", PASSWORD); page.click("#submit")
    page.wait_for_url(BASE + "/")
    for body in ({"symbol": "ABB", "shares": 10, "buy_price": 10000}, {"symbol": "TITAN", "watching": True}):
        r = ctx.request.post(BASE + "/api/holdings", data=body, headers={"Origin": BASE})
        print("INFO add", body["symbol"], r.status)

    # the app is installable
    manifest = ctx.request.get(BASE + "/manifest.webmanifest")
    check(manifest.ok and json.loads(manifest.text())["display"] == "standalone", "the web app manifest loads (standalone)")
    for icon in ("/icons/icon-192.png", "/icons/icon-512.png", "/icons/apple-touch-icon.png"):
        check(ctx.request.get(BASE + icon).ok, f"{icon} loads")

    pages = [("login", "/login.html", "#login-form"), ("search", "/", "#recent-list li"),
             ("report", "/report.html?symbol=ABB", ".q-row"), ("holdings", "/holdings.html", "table.holdings tbody tr"),
             ("market", "/market.html", ".index-card")]
    for width in WIDTHS:
        page.set_viewport_size({"width": width, "height": 800})
        for name, path, ready in pages:
            if name == "login":
                ctx2 = browser.new_context(viewport={"width": width, "height": 800}, device_scale_factor=2, is_mobile=True, has_touch=True)
                pg = ctx2.new_page(); pg.goto(BASE + path)
            else:
                pg = page; pg.goto(BASE + path)
            pg.wait_for_selector(ready, timeout=120000)
            pg.wait_for_timeout(300)
            o = pg.evaluate(OVERFLOW_JS)
            check(o["scrollWidth"] <= o["vw"] and not o["offenders"], f"{name} @ {width}px: no sideways scroll or clipped content {o if o['offenders'] or o['scrollWidth'] > o['vw'] else ''}")
            t = pg.evaluate(TARGETS_JS)
            check(not t["small"], f"{name} @ {width}px: tap targets at least 44px {t['small'] if t['small'] else ''}")
            check(not t["fonts"], f"{name} @ {width}px: inputs at least 16px {t['fonts'] if t['fonts'] else ''}")
            if width == 375:
                pg.screenshot(path=f"{OUT}/m375_{name}.png", full_page=True)
            if name == "login":
                ctx2.close()

    # bottom tab bar and dialog as a bottom sheet
    for width, expect_bar in ((390, True), (768, False), (1280, False)):
        page.set_viewport_size({"width": width, "height": 800})
        page.goto(BASE + "/holdings.html"); page.wait_for_selector("table.holdings tbody tr")
        pos = page.evaluate("getComputedStyle(document.querySelector('.nav')).position")
        icons = page.evaluate("getComputedStyle(document.querySelector('.nav-icon')).display")
        if expect_bar:
            check(pos == "fixed" and icons == "block", f"@ {width}px the pages are a fixed bottom tab bar with icons")
            box = page.evaluate("(() => { const r = document.querySelector('.nav').getBoundingClientRect(); return [Math.round(r.bottom), innerHeight]; })()")
            check(box[0] == box[1], f"@ {width}px the bar sits at the very bottom {box}")
            check(page.locator(".nav a").count() == 3 and page.locator(".nav-icon").count() == 3, "three tabs, each with an icon")
        else:
            check(pos != "fixed" and icons == "none", f"@ {width}px the normal top navigation is used (no icons)")
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(BASE + "/holdings.html"); page.wait_for_selector("table.holdings tbody tr")
    page.click("#add-btn"); page.wait_for_selector("#stock-dialog[open]")
    d = page.evaluate("(() => { const r = document.getElementById('stock-dialog').getBoundingClientRect(); return {left: r.left, right: r.right, bottom: r.bottom, vh: innerHeight, vw: innerWidth, top: r.top}; })()")
    check(d["left"] == 0 and d["right"] == d["vw"] and abs(d["bottom"] - d["vh"]) < 2, f"the add dialog is a full-width bottom sheet {d}")
    t = page.evaluate(TARGETS_JS)
    check(not t["small"] and not t["fonts"], f"dialog: tap targets and fonts fine {t}")
    page.screenshot(path=f"{OUT}/m390_dialog.png")
    page.keyboard.press("Escape")

    # meta
    meta = page.evaluate("(() => ({ vp: document.querySelector('meta[name=viewport]').content, theme: document.querySelector('meta[name=theme-color]').content, apple: !!document.querySelector('link[rel=apple-touch-icon]') }))()")
    check("viewport-fit=cover" in meta["vp"] and meta["theme"] == "#14141a" and meta["apple"], f"viewport-fit, theme colour and apple icon are set {meta}")
    check(not errors, f"no console errors {errors}")
    browser.close()

print("\nRESULT:", "all checks passed" if not problems else f"{len(problems)} failed")
for pmsg in problems: print(" -", pmsg[:260])

sys.exit(1 if problems else 0)
