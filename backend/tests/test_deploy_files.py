"""Guards on the files that decide how the app is deployed, so a later edit can't quietly weaken them."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ vercel.json (static site + /api proxy + headers)
@pytest.fixture(scope="module")
def vercel():
    return json.loads(read("frontend/vercel.json"))


def headers_for(vercel, source):
    block = next(h for h in vercel["headers"] if h["source"] == source)
    return {h["key"]: h["value"] for h in block["headers"]}


def test_api_calls_are_proxied_to_the_backend_on_the_same_site(vercel):
    rewrite = next(r for r in vercel["rewrites"] if r["source"].startswith("/api/"))
    assert rewrite["source"] == "/api/:path*"
    assert rewrite["destination"].startswith("https://") and rewrite["destination"].endswith("/api/:path*")


def test_every_page_gets_the_security_headers(vercel):
    h = headers_for(vercel, "/(.*)")
    assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY"
    assert "max-age=" in h["Strict-Transport-Security"]
    assert "strict-origin" in h["Referrer-Policy"]
    assert "camera=()" in h["Permissions-Policy"] and "geolocation=()" in h["Permissions-Policy"]


def test_the_content_security_policy_is_strict(vercel):
    csp = headers_for(vercel, "/(.*)")["Content-Security-Policy"]
    directives = {d.split()[0]: d.split()[1:] for d in csp.split(";") if d.strip()}
    assert directives["default-src"] == ["'self'"]
    assert directives["script-src"] == ["'self'"], "scripts only from our own files"
    assert "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp and "*" not in csp.replace("'self'", "")
    assert directives["connect-src"] == ["'self'"], "the page may only talk to its own site (the /api proxy)"
    assert directives["frame-ancestors"] == ["'none'"] and directives["object-src"] == ["'none'"]
    assert directives["style-src"] == ["'self'", "https://fonts.googleapis.com"]
    assert directives["font-src"] == ["https://fonts.gstatic.com"]
    assert directives["base-uri"] == ["'self'"] and directives["form-action"] == ["'self'"]


def test_the_policy_matches_what_the_pages_actually_load():
    """Inline script or style blocks and event-handler attributes would be blocked by the policy above."""
    for page in (ROOT / "frontend").glob("*.html"):
        html = page.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", html), f"{page.name} has an inline script"
        assert "<style" not in html, f"{page.name} has an inline style block"
        assert not re.search(r"\son\w+\s*=", html), f"{page.name} has an inline event handler"
        assert not re.search(r'\sstyle\s*=\s*"', html), f"{page.name} has an inline style attribute"
        for src in re.findall(r'(?:src|href)="(https?://[^"]+)"', html):
            assert src.startswith(("https://fonts.googleapis.com", "https://fonts.gstatic.com")), f"{page.name} loads {src}"


def test_scripts_and_styles_are_revalidated_so_a_deploy_shows_up_at_once(vercel):
    assert "must-revalidate" in headers_for(vercel, "/(css|js)/(.*)")["Cache-Control"]


def test_the_placeholder_backend_address_is_called_out(vercel):
    """The file ships with a placeholder; the deploy guide tells you to replace it. This only fails loudly
    in CI if someone forgets, by being the one test that expects the placeholder or a real https domain."""
    dest = next(r for r in vercel["rewrites"] if r["source"] == "/api/:path*")["destination"]
    assert "REPLACE-WITH-YOUR-RAILWAY-DOMAIN" in dest or re.match(r"https://[a-z0-9.-]+\.[a-z]{2,}/api/:path\*$", dest)


# ------------------------------------------------------------------ Dockerfile and .dockerignore
def test_the_image_runs_as_a_normal_user_on_the_port_the_host_provides():
    docker = read("Dockerfile")
    assert "USER appuser" in docker and "${PORT" in docker and "--host ::" in docker
    assert "backend.app.main:app" in docker and "--proxy-headers" in docker
    assert "COPY requirements.txt" in docker and "COPY backend" in docker
    assert ".env" not in docker


def test_secrets_and_test_tooling_stay_out_of_the_image():
    ignored = {line.strip() for line in read(".dockerignore").splitlines() if line.strip() and not line.startswith("#")}
    assert {".env", ".env.*", "venv/", ".git/", "backend/tests/", "*.sqlite3", "test.py"} <= ignored
    assert "!.env.example" in ignored


def test_the_company_snapshot_ships_with_the_backend():
    assert (ROOT / "backend" / "data" / "EQUITY_L.csv").exists()
    assert "backend/data" not in read(".dockerignore")


# ------------------------------------------------------------------ dependencies
def test_runtime_dependencies_are_pinned_and_test_tools_are_not_in_them():
    lines = [l.strip() for l in read("requirements.txt").splitlines() if l.strip() and not l.startswith("#")]
    assert lines and all("==" in l for l in lines), "every runtime dependency is pinned to an exact version"
    names = {l.split("==")[0].lower() for l in lines}
    assert {"fastapi", "uvicorn", "supabase", "httpx"} <= names
    assert not names & {"pytest", "playwright", "pglast", "pyjwt"}


def test_the_dev_requirements_include_the_runtime_ones_and_the_test_tools():
    dev = read("requirements-dev.txt")
    assert "-r requirements.txt" in dev and "pytest==" in dev and "PyJWT==" in dev


def test_env_example_lists_the_settings_and_no_secret_keys():
    text = read(".env.example")
    for name in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "COOKIE_SECURE", "ALLOWED_ORIGINS", "OPENAI_API_KEY"):
        assert name in text
    assert not re.search(r"^\s*SUPABASE_(SECRET|SERVICE)", text, re.M)
