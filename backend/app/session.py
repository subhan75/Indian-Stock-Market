"""The HTTP side of login: cookies, the guard every protected route uses, and the Origin (CSRF) check.

The Supabase tokens live in two HttpOnly cookies, so page JavaScript can never read them. The guard turns a valid
session into a per-request Supabase store that acts as that user (so Row Level Security applies), and renews an access
token that is about to expire.
"""
import time

from fastapi import Request, Response
from fastapi.concurrency import run_in_threadpool

from . import auth, config, store
from .errors import DB_DOWN, SIGN_IN, ApiError
from .store_supabase import SupabaseStore, make_client

COOKIE_MAX_AGE = 60 * 60 * 24 * 30          # 30 days; the refresh token inside decides how long a session really lasts
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def cookie_names() -> tuple[str, str]:
    """(access, refresh). `__Host-` makes browsers insist on Secure + no Domain + Path=/, so it is used whenever
    cookies are Secure (production); local http development uses plain names."""
    prefix = "__Host-" if config.COOKIE_SECURE else ""
    return f"{prefix}sb-access", f"{prefix}sb-refresh"


def set_session_cookies(response: Response, tokens: auth.Tokens) -> None:
    access, refresh = cookie_names()
    for name, value in ((access, tokens.access_token), (refresh, tokens.refresh_token)):
        response.set_cookie(name, value, max_age=COOKIE_MAX_AGE, path="/", httponly=True,
                            secure=config.COOKIE_SECURE, samesite="lax")


def clear_session_cookies(response: Response) -> None:
    for name in cookie_names():
        response.delete_cookie(name, path="/", httponly=True, secure=config.COOKIE_SECURE, samesite="lax")


# ----------------------------------------------------------------------------- who is calling?
def _unauthorized() -> ApiError:
    return ApiError("unauthorized", SIGN_IN)


def _unavailable() -> ApiError:
    return ApiError("source_unavailable", DB_DOWN)


def resolve(access_token: str | None, refresh_token: str | None) -> tuple[auth.Identity, auth.Tokens | None]:
    """The signed-in user for these cookies, plus fresh tokens if the session had to be renewed.
    Blocking (talks to Supabase); call it in a worker thread."""
    try:
        if access_token:
            expires_at = auth.token_expiry(access_token)
            comfortably_valid = expires_at is None or expires_at - time.time() > auth.REFRESH_MARGIN_SECONDS
            if comfortably_valid:
                try:
                    return auth.verify(access_token), None
                except auth.SessionExpired:
                    pass                                    # rejected (for example signed out): try renewing below
            elif not refresh_token:
                return auth.verify(access_token), None      # nearly expired but nothing to renew with: use it
        if refresh_token:
            try:
                tokens = auth.refresh(refresh_token)
            except auth.SessionExpired:
                # An access token that is close to expiry may still be good even though renewal was refused.
                if access_token and (auth.token_expiry(access_token) or 0) > time.time():
                    return auth.verify(access_token), None
                raise
            return auth.Identity(tokens.user_id, tokens.email, tokens.access_token), tokens
    except auth.SessionExpired:
        raise _unauthorized() from None
    except auth.AuthUnavailable:
        raise _unavailable() from None
    raise _unauthorized()


async def require_user(request: Request, response: Response) -> auth.Identity:
    """FastAPI dependency for every protected route. Everything after it, including the store, acts as this user."""
    access, refresh = cookie_names()
    identity, renewed = await run_in_threadpool(resolve, request.cookies.get(access), request.cookies.get(refresh))
    if renewed is not None:
        set_session_cookies(response, renewed)
    # Bound for the rest of this request only: each request runs in its own context.
    store.bind(SupabaseStore(make_client(identity.access_token), identity.user_id))
    return identity


# ----------------------------------------------------------------------------- cross-site request protection
def allowed_origins(request: Request) -> set[str]:
    own_scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    own_host = request.headers.get("x-forwarded-host", request.headers.get("host", "")).split(",")[0].strip()
    allowed = set(config.ALLOWED_ORIGINS)
    if own_host:
        allowed.add(f"{own_scheme}://{own_host}")
    return allowed


async def check_origin(request: Request) -> None:
    """Changes must come from our own site (or an allowed one). Browsers always send Origin on POST, PUT and DELETE;
    a script without one carries no cookies of ours, so it is let through to be refused by the sign-in check."""
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in allowed_origins(request):
        raise ApiError("forbidden", "That request wasn't allowed from this site.")
    if request.headers.get("content-length", "0") not in {"", "0"} and \
            "application/json" not in request.headers.get("content-type", "").lower():
        raise ApiError("bad_request", "That request wasn't valid.")
