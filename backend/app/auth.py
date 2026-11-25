"""Sign in, token checks, renewal and sign-out against Supabase Auth (email + password).

Security notes:
- Tokens are never logged. Error text from Supabase is reduced to a short code before it reaches a log line.
- Every access token is checked with Supabase itself (`get_user`), not just decoded. That also catches sessions that
  were signed out, at the price of one request per token per `AUTH_VERIFY_TTL_SECONDS`.
- Refresh tokens are single-use. Several simultaneous requests carrying the same expired access token would each try
  to renew it and the second attempt would end the whole session, so renewals are serialised per token and the new
  session is shared for a few seconds.
"""
import base64
import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass

import httpx
from supabase_auth.errors import AuthApiError, AuthError, AuthSessionMissingError

from . import config, memcache
from .store import StoreError
from .store_supabase import make_client

log = logging.getLogger("stock_analyst.auth")

REFRESH_MARGIN_SECONDS = 60        # renew an access token that has less than this left
REUSE_WINDOW_SECONDS = 20          # share a just-renewed session with simultaneous requests this long
RATE_LIMIT_CODES = {"over_request_rate_limit", "over_email_send_rate_limit", "over_sms_send_rate_limit"}


class AuthUnavailable(Exception):
    """Supabase Auth couldn't be reached or isn't configured."""


class InvalidCredentials(Exception):
    """Wrong email or password (the same for an unknown email, on purpose)."""


class RateLimited(Exception):
    """Supabase says too many attempts."""


class SessionExpired(Exception):
    """The access or refresh token is no longer good. The user has to sign in again."""


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: int
    user_id: str
    email: str


@dataclass(frozen=True)
class Identity:
    user_id: str
    email: str
    access_token: str


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def token_expiry(access_token: str) -> int | None:
    """The `exp` claim, read WITHOUT verifying the signature. Only used to decide when to renew; whether the token
    is genuine is always decided by Supabase (see `verify`)."""
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        return int(exp) if exp is not None else None
    except (IndexError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _client(access_token: str | None = None):
    try:
        return make_client(access_token)
    except StoreError as exc:
        raise AuthUnavailable("Supabase isn't configured.") from exc


def _tokens(session) -> Tokens:
    return Tokens(session.access_token, session.refresh_token,
                  int(session.expires_at or (time.time() + session.expires_in)),
                  session.user.id, session.user.email or "")


def _status(exc: AuthError) -> int:
    return getattr(exc, "status", 0) or 0


# ----------------------------------------------------------------------------- sign in
def sign_in(email: str, password: str) -> Tokens:
    try:
        response = _client().auth.sign_in_with_password({"email": email, "password": password})
    except AuthApiError as exc:
        if _status(exc) == 429 or exc.code in RATE_LIMIT_CODES:
            raise RateLimited() from exc
        if 400 <= _status(exc) < 500:
            log.info("Sign-in refused (%s)", exc.code or _status(exc))
            raise InvalidCredentials() from exc
        raise AuthUnavailable("Sign-in service error.") from exc
    except (AuthError, httpx.HTTPError, OSError) as exc:
        raise AuthUnavailable("Sign-in service unreachable.") from exc
    if response.session is None or response.user is None:
        raise InvalidCredentials()
    return _tokens(response.session)


# ----------------------------------------------------------------------------- is this token good?
def verify(access_token: str) -> Identity:
    key = _digest(access_token)
    hit = memcache.verified.get(key)
    if hit and time.monotonic() - hit[1] < config.AUTH_VERIFY_TTL_SECONDS:
        return hit[0]
    try:
        response = _client().auth.get_user(access_token)
    except AuthSessionMissingError as exc:
        raise SessionExpired() from exc
    except AuthApiError as exc:
        if 400 <= _status(exc) < 500:
            raise SessionExpired() from exc
        raise AuthUnavailable("Sign-in service error.") from exc
    except (AuthError, httpx.HTTPError, OSError) as exc:
        raise AuthUnavailable("Sign-in service unreachable.") from exc
    user = response.user if response else None
    if user is None or user.is_anonymous or user.role not in (None, "authenticated"):
        raise SessionExpired()
    identity = Identity(user.id, user.email or "", access_token)
    memcache.verified.put(key, (identity, time.monotonic()))
    return identity


# ----------------------------------------------------------------------------- renewal
_refresh_locks = [threading.Lock() for _ in range(64)]


def refresh(refresh_token: str) -> Tokens:
    key = _digest(refresh_token)
    with _refresh_locks[int(key[:8], 16) % len(_refresh_locks)]:
        hit = memcache.refreshed.get(key)
        if hit and time.monotonic() - hit[1] < REUSE_WINDOW_SECONDS:
            return hit[0]
        try:
            response = _client().auth.refresh_session(refresh_token)
        except AuthSessionMissingError as exc:
            raise SessionExpired() from exc
        except AuthApiError as exc:
            if 400 <= _status(exc) < 500:
                log.info("Session renewal refused (%s)", exc.code or _status(exc))
                raise SessionExpired() from exc
            raise AuthUnavailable("Sign-in service error.") from exc
        except (AuthError, httpx.HTTPError, OSError) as exc:
            raise AuthUnavailable("Sign-in service unreachable.") from exc
        if response.session is None:
            raise SessionExpired()
        tokens = _tokens(response.session)
        memcache.refreshed.put(key, (tokens, time.monotonic()))
        return tokens


# ----------------------------------------------------------------------------- sign out
def sign_out(access_token: str) -> None:
    """End THIS device's session (scope "local"); other devices stay signed in. Never raises: the cookies are cleared
    whatever happens, and a failed revoke only means the session lasts until its token expires."""
    memcache.verified.pop(_digest(access_token))
    try:
        _client().auth.admin.sign_out(access_token, "local")
    except Exception as exc:  # noqa: BLE001 - best effort by design
        log.info("Sign-out request failed (ignored): %s", type(exc).__name__)
