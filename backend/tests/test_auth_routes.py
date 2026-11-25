import logging
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import auth, config, ratelimit, report, session, store_supabase
from backend.app.main import app
from backend.app.sources import nse
from fake_postgrest import error as rest_error
from fake_supabase import FakeSupabase, gotrue_error

EMAIL, PASSWORD = "you@example.com", "correct horse battery staple"
OTHER_EMAIL = "partner@example.com"
SITE = "https://testserver"
JSON_HEADERS = {"Origin": SITE}
SIGN_IN = {"error": {"code": "unauthorized", "message": "Please sign in."}}


@pytest.fixture
def supabase(monkeypatch, real_sign_in):
    fake = FakeSupabase()
    fake.auth.add_user(EMAIL, PASSWORD)
    fake.auth.add_user(OTHER_EMAIL, PASSWORD)
    monkeypatch.setattr(config, "SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_PUBLISHABLE_KEY", "sb_publishable_TEST")
    monkeypatch.setattr(config, "COOKIE_SECURE", True)
    monkeypatch.setattr(config, "ALLOWED_ORIGINS", [])
    monkeypatch.setattr(config, "DB_RETRY_READS", False)
    monkeypatch.setattr(store_supabase, "_shared_http", fake.http_client())
    monkeypatch.setattr(report, "get_report", lambda *a, **k: None)             # no real report building here
    nse.store_companies([{"symbol": "ABB", "name": "ABB India Limited", "series": "EQ", "isin": "x"},
                         {"symbol": "TITAN", "name": "Titan Company Limited", "series": "EQ", "isin": "y"}])
    return fake


@pytest.fixture
def web(supabase):
    clients = []

    def make(**kwargs):
        c = TestClient(app, base_url=SITE, **kwargs)
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.close()


def login(client, email=EMAIL, password=PASSWORD, **headers):
    return client.post("/api/auth/login", json={"email": email, "password": password},
                       headers={**JSON_HEADERS, **headers})


def cookie_headers(response) -> list[str]:
    return response.headers.get_list("set-cookie")


def signed_in(web, email=EMAIL):
    client = web()
    assert login(client, email).status_code == 200
    return client


def hold_body(symbol="ABB"):
    return {"symbol": symbol, "shares": 10, "buy_price": 100.0}


# ------------------------------------------------------------------ logging in
def test_login_returns_only_the_email_and_sets_secure_httponly_cookies(web):
    r = login(web())
    assert r.status_code == 200 and r.json() == {"user": {"email": EMAIL}}
    cookies = cookie_headers(r)
    assert len(cookies) == 2
    for c in cookies:
        assert c.startswith(("__Host-sb-access=", "__Host-sb-refresh="))
        assert "HttpOnly" in c and "Secure" in c and "SameSite=lax" in c and "Path=/" in c and "Domain" not in c
    assert "access_token" not in r.text and "refresh_token" not in r.text


def test_local_http_development_uses_plain_cookie_names_without_secure(web, monkeypatch):
    monkeypatch.setattr(config, "COOKIE_SECURE", False)
    r = login(web())
    names = [c.split("=")[0] for c in cookie_headers(r)]
    assert names == ["sb-access", "sb-refresh"] and not any("Secure" in c for c in cookie_headers(r))
    assert all("HttpOnly" in c for c in cookie_headers(r))


def test_email_is_trimmed_and_case_insensitive(web):
    assert login(web(), "  You@Example.COM ").status_code == 200


@pytest.mark.parametrize("body", [{}, {"email": EMAIL}, {"password": PASSWORD}, {"email": "", "password": ""},
                                  {"email": "   ", "password": "x"}, {"email": 5, "password": "x"},
                                  {"email": EMAIL, "password": ["x"]}, {"email": "a" * 300, "password": "x"},
                                  {"email": EMAIL, "password": "p" * 300}, [], "text"])
def test_missing_or_malformed_credentials_get_a_plain_400(web, body):
    r = web().post("/api/auth/login", json=body, headers=JSON_HEADERS)
    assert r.status_code == 400
    assert r.json() == {"error": {"code": "bad_request", "message": "Enter your email and password."}}


def test_wrong_password_and_unknown_email_look_exactly_alike_and_set_no_cookies(web):
    wrong = login(web(), password="nope")
    unknown = login(web(), "nobody@example.com", "whatever")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"error": {"code": "unauthorized", "message": "Wrong email or password."}}
    assert cookie_headers(wrong) == cookie_headers(unknown) == []


def test_five_wrong_attempts_lock_that_email_even_for_the_right_password(web):
    client = web()
    for _ in range(5):
        assert login(client, password="nope").status_code == 401
    locked = login(client, password=PASSWORD)
    assert locked.status_code == 429
    assert locked.json() == {"error": {"code": "rate_limited", "message": "Too many attempts. Try again in a few minutes."}}
    assert login(client, OTHER_EMAIL).status_code == 200                 # someone else is not locked out


def test_a_successful_login_clears_the_failure_count(web):
    client = web()
    for _ in range(4):
        login(client, password="nope")
    assert login(client).status_code == 200
    for _ in range(4):
        assert login(client, password="nope").status_code == 401         # counting started over


def test_many_failures_from_one_address_block_that_address(web):
    client = web()
    for i in range(25):
        login(client, f"user{i}@example.com", "x", **{"X-Forwarded-For": "203.0.113.9"})
    r = login(client, EMAIL, PASSWORD, **{"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 429
    assert login(client, EMAIL, PASSWORD, **{"X-Forwarded-For": "198.51.100.1"}).status_code == 200


def test_supabase_rate_limiting_is_passed_on_as_the_same_friendly_429(web, supabase):
    supabase.auth.rate_limited = True
    r = login(web())
    assert r.status_code == 429 and r.json()["error"]["message"] == "Too many attempts. Try again in a few minutes."


def test_an_auth_outage_is_a_503_not_a_wrong_password(web, supabase):
    supabase.auth.fail_always = httpx.ConnectError("down")
    r = login(web())
    assert r.status_code == 503
    assert r.json() == {"error": {"code": "source_unavailable",
                                  "message": "Sign-in isn't available right now. Try again in a minute."}}
    assert ratelimit.by_email.seconds_until_allowed(EMAIL) == 0, "an outage must not count against the user"


def test_an_unconfigured_project_is_a_503(web, monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", "")
    assert login(web()).status_code == 503


# ------------------------------------------------------------------ who am I, and the guard
def test_me_names_the_signed_in_user(web):
    client = signed_in(web)
    r = client.get("/api/auth/me")
    assert r.status_code == 200 and r.json() == {"user": {"email": EMAIL}}


def test_me_without_a_session_or_with_junk_cookies_is_401(web):
    assert web().get("/api/auth/me").json() == SIGN_IN
    junk = web(cookies={"__Host-sb-access": "not.a.token", "__Host-sb-refresh": "garbage"})
    r = junk.get("/api/auth/me")
    assert r.status_code == 401 and r.json() == SIGN_IN


def all_api_routes() -> list[tuple[str, str]]:
    """Every (METHOD, path template) the app serves under /api, taken from the app's own schema."""
    paths = app.openapi()["paths"]
    return [(method.upper(), path) for path, methods in paths.items() if path.startswith("/api")
            for method in methods if method.upper() not in {"HEAD", "OPTIONS"}]


def test_every_data_route_is_closed_without_a_session(web):
    """Walks the real route table, so a route added later without the guard fails here."""
    open_routes = {"/api/health", "/api/auth/login", "/api/auth/logout"}
    client, checked = web(), []
    for method, template in all_api_routes():
        if template in open_routes:
            continue
        body = {} if method in {"POST", "PUT", "PATCH"} else None
        r = client.request(method, template.replace("{symbol}", "ABB"), json=body, headers=JSON_HEADERS)
        assert r.status_code == 401 and r.json() == SIGN_IN, f"{method} {template} is not protected"
        checked.append(f"{method} {template}")
    assert len(checked) >= 10
    assert {"GET /api/holdings", "POST /api/refresh-all", "GET /api/market/today", "GET /api/reports/{symbol}",
            "GET /api/stocks/search", "GET /api/auth/me"} <= set(checked)
    assert web().get("/api/health").json() == {"ok": True}


def test_the_only_open_routes_are_health_login_and_logout():
    opened = {path for method, path in all_api_routes() if path in {"/api/health", "/api/auth/login", "/api/auth/logout"}}
    assert opened == {"/api/health", "/api/auth/login", "/api/auth/logout"}


def test_the_interactive_docs_and_schema_are_not_published(web):
    client = web()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code != 200


def test_the_app_is_a_real_session_with_saved_data_end_to_end(web, supabase):
    client = signed_in(web)
    assert client.get("/api/holdings").json()["rows"] == []
    assert client.post("/api/holdings", json=hold_body(), headers=JSON_HEADERS).status_code == 201
    rows = client.get("/api/holdings").json()["rows"]
    assert [r["symbol"] for r in rows] == ["ABB"]
    saved = supabase.rest.tables["holdings"]
    assert len(saved) == 1 and saved[0]["user_id"] == supabase.auth.users[EMAIL]["id"]


def test_two_people_never_see_each_others_stocks(web, supabase):
    mine, theirs = signed_in(web, EMAIL), signed_in(web, OTHER_EMAIL)
    mine.post("/api/holdings", json=hold_body("ABB"), headers=JSON_HEADERS)
    assert theirs.get("/api/holdings").json()["rows"] == []
    assert theirs.put("/api/holdings/ABB", json={"shares": 1, "buy_price": 1}, headers=JSON_HEADERS).status_code == 404
    assert theirs.delete("/api/holdings/ABB", headers=JSON_HEADERS).status_code == 404
    theirs.post("/api/holdings", json={"symbol": "TITAN", "watching": True}, headers=JSON_HEADERS)
    assert [r["symbol"] for r in mine.get("/api/holdings").json()["rows"]] == ["ABB"]
    assert [r["symbol"] for r in theirs.get("/api/holdings").json()["rows"]] == ["TITAN"]
    assert mine.get("/api/holdings").json()["rows"][0]["shares"] == 10


def test_the_database_acts_as_the_user_with_their_own_token(web, supabase):
    client = signed_in(web)
    client.get("/api/holdings")
    rest = [r for r in supabase.requests if r.url.path.startswith("/rest/v1")]
    assert rest and all(r.headers["apikey"] == "sb_publishable_TEST" for r in rest)
    tokens = {r.headers["authorization"] for r in rest}
    assert len(tokens) == 1 and "sb_publishable_TEST" not in next(iter(tokens))


# ------------------------------------------------------------------ renewing an expiring session
def test_a_token_about_to_expire_is_renewed_and_the_cookies_updated(web, supabase):
    supabase.auth.access_ttl = 30                                   # inside the 60 s renewal margin
    client = signed_in(web)
    old_cookie = client.cookies.get("__Host-sb-access")
    supabase.auth.access_ttl = 3600
    r = client.get("/api/auth/me")
    assert r.status_code == 200 and supabase.auth.count("refresh") == 1
    assert len(cookie_headers(r)) == 2 and client.cookies.get("__Host-sb-access") != old_cookie
    assert client.get("/api/auth/me").status_code == 200 and supabase.auth.count("refresh") == 1


def test_an_expired_token_with_a_good_refresh_token_keeps_you_signed_in(web, supabase):
    supabase.auth.access_ttl = -10
    client = signed_in(web)
    supabase.auth.access_ttl = 3600
    assert client.get("/api/holdings").status_code == 200
    assert supabase.auth.count("refresh") == 1


def test_simultaneous_requests_at_expiry_all_succeed_and_renew_once(web, supabase):
    """Exit criterion 2.4: refresh tokens are single-use, so a race must not end the session."""
    supabase.auth.access_ttl = -10
    first = signed_in(web)
    jar = dict(first.cookies)
    supabase.auth.access_ttl = 3600

    def call(_):
        with TestClient(app, base_url=SITE, cookies=jar) as c:
            return c.get("/api/auth/me").status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(call, range(8)))
    assert codes == [200] * 8
    assert supabase.auth.count("refresh") == 1
    assert not any(s["revoked"] for s in supabase.auth.sessions.values())


def test_a_dead_refresh_token_means_sign_in_again(web, supabase):
    supabase.auth.access_ttl = -10
    client = signed_in(web)
    for record in supabase.auth.refresh_tokens.values():
        record["used"] = True
    r = client.get("/api/auth/me")
    assert r.status_code == 401 and r.json() == SIGN_IN


def test_a_nearly_expired_token_is_still_used_if_renewal_is_refused(web, supabase):
    supabase.auth.access_ttl = 30
    client = signed_in(web)
    supabase.auth.refresh_tokens.clear()                 # renewal is refused, but the session itself is still alive
    assert client.get("/api/auth/me").status_code == 200


def test_an_auth_outage_during_a_request_is_a_503_and_keeps_the_cookies(web, supabase, monkeypatch):
    client = signed_in(web)
    monkeypatch.setattr(config, "AUTH_VERIFY_TTL_SECONDS", 0)
    supabase.auth.fail_always = httpx.ConnectError("down")
    r = client.get("/api/auth/me")
    assert r.status_code == 503 and cookie_headers(r) == []


def test_a_token_expiring_between_the_check_and_the_database_is_a_401(web, supabase):
    client = signed_in(web)
    client.get("/api/auth/me")                                       # the check is now cached
    supabase.rest.fail_always = rest_error(401, "PGRST301", "JWT expired")
    r = client.get("/api/holdings")
    assert r.status_code == 401 and r.json() == SIGN_IN


def test_the_database_being_down_is_a_plain_503(web, supabase):
    client = signed_in(web)
    supabase.rest.fail_always = httpx.ConnectError("down")
    r = client.get("/api/holdings")
    assert r.status_code == 503
    assert r.json() == {"error": {"code": "source_unavailable",
                                  "message": "The database isn't reachable right now. Try again in a minute."}}


# ------------------------------------------------------------------ logging out
def test_logout_clears_both_cookies_and_ends_the_session(web, supabase):
    client = signed_in(web)
    jar = dict(client.cookies)
    r = client.post("/api/auth/logout", headers=JSON_HEADERS)
    assert r.status_code == 200 and r.json() == {"ok": True}
    cleared = cookie_headers(r)
    assert len(cleared) == 2 and all("Max-Age=0" in c or "expires=" in c.lower() for c in cleared)
    assert client.get("/api/auth/me").status_code == 401
    replay = web(cookies=jar)                                        # someone who kept a copy of the old cookies
    assert replay.get("/api/auth/me").status_code == 401, "the old cookies must not work after logout"


def test_logging_out_while_signed_out_is_fine(web):
    r = web().post("/api/auth/logout", headers=JSON_HEADERS)
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_logout_signs_out_this_device_only(web):
    phone, laptop = signed_in(web), signed_in(web)
    phone.post("/api/auth/logout", headers=JSON_HEADERS)
    assert phone.get("/api/auth/me").status_code == 401
    assert laptop.get("/api/auth/me").status_code == 200


def test_logout_succeeds_even_if_supabase_is_down(web, supabase):
    client = signed_in(web)
    supabase.auth.fail_always = httpx.ConnectError("down")
    r = client.post("/api/auth/logout", headers=JSON_HEADERS)
    assert r.status_code == 200 and len(cookie_headers(r)) == 2


# ------------------------------------------------------------------ cross-site request protection
def test_a_change_from_another_site_is_refused(web):
    client = signed_in(web)
    for method, path, body in (("POST", "/api/holdings", hold_body()), ("PUT", "/api/holdings/ABB", hold_body()),
                               ("DELETE", "/api/holdings/ABB", None), ("POST", "/api/refresh-all", None),
                               ("POST", "/api/auth/logout", None)):
        r = client.request(method, path, json=body, headers={"Origin": "https://evil.example"})
        assert r.status_code == 403, (method, path)
        assert r.json() == {"error": {"code": "forbidden", "message": "That request wasn't allowed from this site."}}
    assert client.get("/api/holdings").json()["rows"] == []


def test_reading_from_another_site_is_not_blocked_by_this_check(web):
    client = signed_in(web)
    assert client.get("/api/auth/me", headers={"Origin": "https://evil.example"}).status_code == 200


def test_the_configured_site_and_our_own_address_are_allowed(web, monkeypatch):
    client = signed_in(web)
    monkeypatch.setattr(config, "ALLOWED_ORIGINS", ["https://my-app.vercel.app"])
    assert client.post("/api/holdings", json=hold_body("ABB"),
                       headers={"Origin": "https://my-app.vercel.app"}).status_code == 201
    assert client.post("/api/holdings", json=hold_body("TITAN"), headers={"Origin": SITE}).status_code == 201
    assert client.delete("/api/holdings/ABB", headers={"Origin": "https://my-app.vercel.app/"}).status_code == 200


def test_through_the_vercel_proxy_the_forwarded_host_counts_as_our_site(web):
    client = signed_in(web)
    headers = {"Origin": "https://my-app.vercel.app", "X-Forwarded-Host": "my-app.vercel.app",
               "X-Forwarded-Proto": "https"}
    assert client.post("/api/holdings", json=hold_body(), headers=headers).status_code == 201


def test_a_request_without_an_origin_header_is_not_blocked(web):
    client = signed_in(web)
    assert client.post("/api/holdings", json=hold_body()).status_code == 201


def test_a_body_that_is_not_json_is_refused(web):
    client = signed_in(web)
    r = client.post("/api/holdings", content="symbol=ABB&shares=1", headers={**JSON_HEADERS,
                    "Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"


def test_the_login_route_has_the_same_protection(web):
    r = web().post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD},
                   headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and cookie_headers(r) == []


# ------------------------------------------------------------------ secrets stay out of logs and responses
def test_no_token_or_password_ever_reaches_a_log_line(web, supabase, caplog):
    caplog.set_level(logging.DEBUG)
    supabase.auth.access_ttl = 30
    client = signed_in(web)
    tokens = {client.cookies.get("__Host-sb-access"), client.cookies.get("__Host-sb-refresh")}
    client.get("/api/auth/me")                                       # renews
    tokens |= {client.cookies.get("__Host-sb-access"), client.cookies.get("__Host-sb-refresh")}
    login(web(), password="wrong-password-123")
    client.post("/api/auth/logout", headers=JSON_HEADERS)
    text = "\n".join(f"{r.getMessage()} {r.args} {r.exc_text}" for r in caplog.records)
    for secret in tokens | {PASSWORD, "wrong-password-123"}:
        assert secret and secret not in text


def test_error_bodies_never_contain_tokens_or_internal_details(web, supabase):
    client = signed_in(web)
    token = client.cookies.get("__Host-sb-access")
    supabase.rest.fail_always = rest_error(500, "XX000", f"internal detail {token}")
    r = client.get("/api/holdings")
    assert token not in r.text and "internal detail" not in r.text and "XX000" not in r.text
