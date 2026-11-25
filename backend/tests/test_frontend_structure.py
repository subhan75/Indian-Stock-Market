"""Static checks on the pages and scripts: accessibility structure and a few safety rules that are easy to break by
accident. The behaviour itself is checked in a real browser by scripts/run_browser_checks.py."""
import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
PAGES = ["index.html", "report.html", "holdings.html", "market.html", "login.html"]
JS = sorted((FRONTEND / "js").glob("*.js"))
CSS = sorted((FRONTEND / "css").glob("*.css"))


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ------------------------------------------------------------------ every page
@pytest.mark.parametrize("page", PAGES)
def test_the_page_has_the_basic_landmarks_and_a_skip_link(page):
    html = text(FRONTEND / page)
    assert '<html lang="en">' in html
    body = html[html.index("<body>"):]
    assert re.match(r'<body>\s*<a class="skip-link" href="#main">Skip to main content</a>', body), "the skip link is the first thing in the page"
    assert len(re.findall(r'<main\b', html)) == 1 and 'id="main"' in html and 'tabindex="-1"' in html
    assert len(re.findall(r"<header\b", html)) == 1 and len(re.findall(r"<footer\b", html)) == 1
    assert "Research aid, not financial advice." in html


@pytest.mark.parametrize("page", PAGES)
def test_the_page_has_a_unique_meaningful_title(page):
    title = re.search(r"<title>(.*?)</title>", text(FRONTEND / page)).group(1)
    assert 8 <= len(title) <= 60 and "Stock Analyst" in title


def test_page_titles_are_different_from_each_other():
    titles = [re.search(r"<title>(.*?)</title>", text(FRONTEND / p)).group(1) for p in PAGES]
    assert len(set(titles)) == len(titles)


@pytest.mark.parametrize("page", ["index.html", "holdings.html", "login.html"])
def test_pages_with_static_content_have_exactly_one_h1(page):
    assert len(re.findall(r"<h1\b", text(FRONTEND / page))) == 1


@pytest.mark.parametrize("page", ["report.html", "market.html"])
def test_pages_that_fill_in_later_never_make_the_whole_main_a_live_region(page):
    """aria-live on <main> would make a screen reader read the whole page out on every change."""
    html = text(FRONTEND / page)
    assert not re.search(r"<main[^>]*aria-live", html)
    assert 'aria-busy="true"' in html


@pytest.mark.parametrize("page", ["index.html", "report.html", "holdings.html", "market.html"])
def test_the_menu_is_a_labelled_navigation_with_the_three_pages(page):
    html = text(FRONTEND / page)
    nav = re.search(r'<nav class="nav" aria-label="Main">(.*?)</nav>', html, re.S).group(1)
    assert re.findall(r'href="([^"]+)"', nav) == ["/", "/holdings.html", "/market.html"]


def test_the_login_form_labels_every_field_and_announces_errors():
    html = text(FRONTEND / "login.html")
    for field in ("email", "password"):
        assert f'<label for="{field}">' in html and f'id="{field}"' in html
    assert 'autocomplete="username"' in html and 'autocomplete="current-password"' in html
    assert 'id="form-error"' in html and 'role="alert"' in html


def test_the_add_dialog_labels_its_fields():
    html = text(FRONTEND / "holdings.html")
    for field in ("stock-input", "shares", "buy-price", "watching"):
        assert f'<label for="{field}">' in html
    assert 'aria-labelledby="dialog-title"' in html


def test_the_stylesheet_gives_keyboard_users_a_visible_focus_and_a_skip_link():
    css = text(FRONTEND / "css" / "app.css")
    assert ":focus-visible" in css and "outline: 3px" in css
    assert ".skip-link:focus" in css and "prefers-reduced-motion: reduce" in css


# ------------------------------------------------------------------ scripts: rules that are easy to break
INNERHTML_ALLOWED = {"ui.js", "labels.js", "loading.js", "nav.js"}        # static icon strings only, never server text


def test_server_text_is_never_put_into_the_page_as_html():
    using = {p.name for p in JS if "innerHTML" in text(p)}
    assert using <= INNERHTML_ALLOWED, f"{sorted(using - INNERHTML_ALLOWED)} use innerHTML; use textContent for server text"
    for p in JS:
        assert "insertAdjacentHTML" not in text(p) and "document.write" not in text(p) and "eval(" not in text(p), p.name


def test_no_token_or_login_data_is_kept_in_browser_storage():
    for p in JS:
        assert "localStorage" not in text(p) and "sessionStorage" not in text(p), p.name
        assert "document.cookie" not in text(p), p.name


def test_links_that_open_a_new_tab_are_created_in_one_place_that_hardens_and_announces_them():
    for p in JS:
        if p.name != "ui.js":
            assert 'target = "_blank"' not in text(p) and "_blank" not in text(p), f"{p.name} builds its own new-tab link"
    ui = text(FRONTEND / "js" / "ui.js")
    assert 'noopener noreferrer' in ui and "opens in a new tab" in ui


def test_pages_stay_eligible_for_the_browsers_instant_back():
    for p in JS:
        s = text(p)
        assert "beforeunload" not in s and "onunload" not in s and re.search(r"addEventListener\(\s*[\"']unload", s) is None, p.name


def test_a_401_always_sends_the_person_to_the_login_page():
    api = text(FRONTEND / "js" / "api.js")
    assert "res.status === 401" in api and "login.html?next=" in api and "credentials: \"same-origin\"" in api


def test_the_login_page_only_returns_to_pages_on_this_site():
    login = text(FRONTEND / "js" / "login.js")
    assert "url.origin === location.origin" in login and 'startsWith("//")' in login


def test_every_slow_operation_uses_the_shared_loader():
    for name in ("search.js", "report.js", "market.js", "holdings.js", "login.js", "nav.js", "combobox.js"):
        assert "./loading.js" in text(FRONTEND / "js" / name), f"{name} doesn't use the shared loader"


# ------------------------------------------------------------------ styles
def test_colours_are_only_defined_in_the_token_file():
    for path in CSS:
        if path.name == "tokens.css":
            continue
        raw = re.findall(r"#[0-9a-fA-F]{3,8}\b", re.sub(r"/\*.*?\*/", "", text(path), flags=re.S))
        assert not raw, f"{path.name} has raw colours {raw}; add a token instead"


def test_text_fields_are_never_smaller_than_16px_on_phones():
    css = text(FRONTEND / "css" / "mobile.css")
    assert "input, select, textarea { font-size: 16px; }" in css
    for path in CSS:
        for size in re.findall(r"input[^{]*\{[^}]*font-size:\s*(\d+)px", text(path)):
            assert int(size) >= 16, f"{path.name}: an input at {size}px makes iPhone Safari zoom in"
