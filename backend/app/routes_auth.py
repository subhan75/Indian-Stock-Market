"""POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me."""
from typing import Any

from fastapi import APIRouter, Body, Depends, Request, Response

from . import auth, ratelimit, session
from .errors import ApiError

router = APIRouter(prefix="/api/auth")

MSG_MISSING = "Enter your email and password."
MSG_WRONG = "Wrong email or password."
MSG_TOO_MANY = "Too many attempts. Try again in a few minutes."
MSG_AUTH_DOWN = "Sign-in isn't available right now. Try again in a minute."
MAX_EMAIL, MAX_PASSWORD = 254, 256


def client_address(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def _credentials(body: Any) -> tuple[str, str]:
    if not isinstance(body, dict):
        raise ApiError("bad_request", MSG_MISSING)
    email, password = body.get("email"), body.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        raise ApiError("bad_request", MSG_MISSING)
    email = email.strip().lower()
    if not email or not password or len(email) > MAX_EMAIL or len(password) > MAX_PASSWORD:
        raise ApiError("bad_request", MSG_MISSING)
    return email, password


@router.post("/login")
def login(request: Request, response: Response, body: Any = Body(...)):
    email, password = _credentials(body)
    address = client_address(request)
    if ratelimit.by_email.seconds_until_allowed(email) or ratelimit.by_address.seconds_until_allowed(address):
        raise ApiError("rate_limited", MSG_TOO_MANY)
    try:
        tokens = auth.sign_in(email, password)
    except auth.InvalidCredentials:
        ratelimit.by_email.record_failure(email)
        ratelimit.by_address.record_failure(address)
        raise ApiError("unauthorized", MSG_WRONG) from None
    except auth.RateLimited:
        raise ApiError("rate_limited", MSG_TOO_MANY) from None
    except auth.AuthUnavailable:
        raise ApiError("source_unavailable", MSG_AUTH_DOWN) from None
    ratelimit.by_email.reset(email)
    session.set_session_cookies(response, tokens)
    return {"user": {"email": tokens.email}}


@router.post("/logout")
def logout(request: Request, response: Response):
    access, _refresh = session.cookie_names()
    token = request.cookies.get(access)
    if token:
        auth.sign_out(token)
    session.clear_session_cookies(response)
    return {"ok": True}


@router.get("/me")
def me(identity: auth.Identity = Depends(session.require_user)):
    return {"user": {"email": identity.email}}
