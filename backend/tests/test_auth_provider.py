import threading
import time

import httpx
import pytest

from backend.app import auth, config, memcache, store_supabase
from fake_supabase import FakeSupabase, gotrue_error

EMAIL, PASSWORD = "you@example.com", "correct horse battery staple"


@pytest.fixture
def supabase(monkeypatch):
    fake = FakeSupabase()
    fake.auth.add_user(EMAIL, PASSWORD)
    monkeypatch.setattr(config, "SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_PUBLISHABLE_KEY", "sb_publishable_TEST")
    monkeypatch.setattr(store_supabase, "_shared_http", fake.http_client())
    return fake


def sign_in(supabase) -> auth.Tokens:
    return auth.sign_in(EMAIL, PASSWORD)


# ------------------------------------------------------------------ sign in
def test_sign_in_returns_the_session(supabase):
    t = sign_in(supabase)
    assert t.email == EMAIL and t.user_id == supabase.auth.users[EMAIL]["id"]
    assert t.access_token.count(".") == 2 and t.refresh_token and t.expires_at > time.time()


def test_wrong_password_and_unknown_email_are_the_same_failure(supabase):
    with pytest.raises(auth.InvalidCredentials):
        auth.sign_in(EMAIL, "nope")
    with pytest.raises(auth.InvalidCredentials):
        auth.sign_in("nobody@example.com", "whatever")


def test_a_rate_limited_sign_in_is_reported_as_such(supabase):
    supabase.auth.rate_limited = True
    with pytest.raises(auth.RateLimited):
        sign_in(supabase)


@pytest.mark.parametrize("failure", [
    gotrue_error(500, "unexpected_failure", "boom"), gotrue_error(503, "x", "down"),
    httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
def test_an_unreachable_or_broken_auth_service_is_unavailable_not_wrong_password(supabase, failure):
    supabase.auth.fail_always = failure
    with pytest.raises(auth.AuthUnavailable):
        sign_in(supabase)


def test_an_unconfigured_project_is_unavailable(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", "")
    with pytest.raises(auth.AuthUnavailable):
        auth.sign_in(EMAIL, PASSWORD)


# ------------------------------------------------------------------ checking a token
def test_a_good_token_identifies_the_user(supabase):
    t = sign_in(supabase)
    who = auth.verify(t.access_token)
    assert (who.user_id, who.email, who.access_token) == (t.user_id, EMAIL, t.access_token)


def test_a_checked_token_is_trusted_briefly_without_asking_again(supabase):
    t = sign_in(supabase)
    auth.verify(t.access_token)
    auth.verify(t.access_token)
    auth.verify(t.access_token)
    assert supabase.auth.count("user") == 1


def test_after_the_cache_window_supabase_is_asked_again(supabase, monkeypatch):
    t = sign_in(supabase)
    auth.verify(t.access_token)
    monkeypatch.setattr(config, "AUTH_VERIFY_TTL_SECONDS", 0)
    auth.verify(t.access_token)
    assert supabase.auth.count("user") == 2


@pytest.mark.parametrize("garbage", ["", "not-a-token", "a.b.c", "x" * 500])
def test_garbage_tokens_are_rejected(supabase, garbage):
    with pytest.raises(auth.SessionExpired):
        auth.verify(garbage)


def test_an_expired_token_is_rejected(supabase):
    supabase.auth.access_ttl = -10
    t = sign_in(supabase)
    with pytest.raises(auth.SessionExpired):
        auth.verify(t.access_token)


def test_a_signed_out_session_is_rejected_even_though_the_token_has_not_expired(supabase, monkeypatch):
    monkeypatch.setattr(config, "AUTH_VERIFY_TTL_SECONDS", 0)
    t = sign_in(supabase)
    auth.verify(t.access_token)
    sid = supabase.auth.session_ids(EMAIL)[0]
    supabase.auth.sessions[sid]["revoked"] = True
    with pytest.raises(auth.SessionExpired):
        auth.verify(t.access_token)


def test_anonymous_users_are_never_accepted(supabase):
    supabase.auth.add_user("anon@example.com", "pw", anonymous=True)
    t = auth.sign_in("anon@example.com", "pw")
    with pytest.raises(auth.SessionExpired):
        auth.verify(t.access_token)


def test_an_auth_outage_while_checking_is_unavailable_not_signed_out(supabase):
    t = sign_in(supabase)
    supabase.auth.fail_always = httpx.ConnectError("down")
    with pytest.raises(auth.AuthUnavailable):
        auth.verify(t.access_token)


def test_a_rejected_check_is_not_cached(supabase):
    supabase.auth.access_ttl = -10
    t = sign_in(supabase)
    for _ in range(2):
        with pytest.raises(auth.SessionExpired):
            auth.verify(t.access_token)
    assert supabase.auth.count("user") == 2 and len(memcache.verified) == 0


# ------------------------------------------------------------------ renewing a session
def test_refresh_returns_new_tokens_and_the_old_refresh_token_is_spent(supabase):
    t = sign_in(supabase)
    renewed = auth.refresh(t.refresh_token)
    assert renewed.refresh_token != t.refresh_token and renewed.access_token != t.access_token
    assert supabase.auth.refresh_tokens[t.refresh_token]["used"] is True


def test_simultaneous_renewals_with_the_same_token_all_succeed_with_one_server_call(supabase):
    t = sign_in(supabase)
    results, errors = [], []

    def renew():
        try:
            results.append(auth.refresh(t.refresh_token))
        except Exception as exc:                         # noqa: BLE001 - the test reports any failure
            errors.append(exc)

    threads = [threading.Thread(target=renew) for _ in range(12)]
    [th.start() for th in threads]
    [th.join() for th in threads]
    assert errors == [] and len(results) == 12
    assert supabase.auth.count("refresh") == 1, "single-use refresh tokens must not be spent twice"
    assert len({r.refresh_token for r in results}) == 1
    assert not any(s["revoked"] for s in supabase.auth.sessions.values()), "the session must survive the race"


def test_a_refresh_token_cannot_be_used_after_the_sharing_window(supabase, monkeypatch):
    t = sign_in(supabase)
    auth.refresh(t.refresh_token)
    monkeypatch.setattr(auth, "REUSE_WINDOW_SECONDS", 0)
    with pytest.raises(auth.SessionExpired):
        auth.refresh(t.refresh_token)


@pytest.mark.parametrize("token", ["", "garbage", "x" * 300])
def test_unknown_refresh_tokens_expire_the_session(supabase, token):
    with pytest.raises(auth.SessionExpired):
        auth.refresh(token)


def test_a_refresh_during_an_outage_is_unavailable(supabase):
    t = sign_in(supabase)
    supabase.auth.fail_always = httpx.ConnectError("down")
    with pytest.raises(auth.AuthUnavailable):
        auth.refresh(t.refresh_token)


# ------------------------------------------------------------------ sign out
def test_sign_out_ends_only_this_devices_session(supabase, monkeypatch):
    monkeypatch.setattr(config, "AUTH_VERIFY_TTL_SECONDS", 0)
    phone, laptop = sign_in(supabase), sign_in(supabase)
    auth.verify(phone.access_token)
    auth.sign_out(phone.access_token)
    with pytest.raises(auth.SessionExpired):
        auth.verify(phone.access_token)
    assert auth.verify(laptop.access_token).email == EMAIL


def test_sign_out_forgets_the_cached_check_immediately(supabase):
    t = sign_in(supabase)
    auth.verify(t.access_token)                          # now cached for the default window
    auth.sign_out(t.access_token)
    with pytest.raises(auth.SessionExpired):
        auth.verify(t.access_token)


@pytest.mark.parametrize("failure", [httpx.ConnectError("down"), gotrue_error(500, "x", "boom"), RuntimeError("odd")])
def test_sign_out_never_raises(supabase, failure):
    t = sign_in(supabase)
    supabase.auth.fail_always = failure
    auth.sign_out(t.access_token)


def test_sign_out_with_a_garbage_token_is_harmless(supabase):
    auth.sign_out("garbage")


# ------------------------------------------------------------------ reading the expiry
def test_token_expiry_reads_the_exp_claim_without_trusting_the_signature(supabase):
    t = sign_in(supabase)
    assert abs(auth.token_expiry(t.access_token) - (time.time() + 3600)) < 5
    assert auth.token_expiry("garbage") is None and auth.token_expiry("a.!!!.c") is None and auth.token_expiry("") is None
