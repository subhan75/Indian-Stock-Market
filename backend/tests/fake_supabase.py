"""A stand-in for a whole Supabase project: Auth (GoTrue) plus the REST API, for offline tests of the REAL clients.

FakeGoTrue emulates what login needs: password sign-in, single-use refresh tokens (reusing one ends the session, as
the real service does outside its short reuse window), `get_user` that notices signed-out sessions, local sign-out,
and expired tokens. Real behaviour is proven separately by running against a real test project.
"""
import json
import secrets
import time
import uuid

import httpx
import jwt

from fake_postgrest import FakePostgrest

SECRET = "gotrue-test-secret-that-is-long-enough-123456"


def gotrue_error(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"code": status, "error_code": code, "msg": message})


class FakeGoTrue:
    def __init__(self) -> None:
        self.users: dict[str, dict] = {}                 # email -> {"id","password","anonymous"}
        self.sessions: dict[str, dict] = {}              # session id -> {"email","revoked"}
        self.refresh_tokens: dict[str, dict] = {}        # refresh token -> {"sid","used"}
        self.calls: list[str] = []                       # "password", "refresh", "user", "logout"
        self.access_ttl = 3600
        self.rate_limited = False
        self.fail_always: httpx.Response | Exception | None = None

    # ------------------------------------------------------------------ setup helpers
    def add_user(self, email: str, password: str, anonymous: bool = False) -> str:
        user_id = str(uuid.uuid4())
        self.users[email.lower()] = {"id": user_id, "password": password, "anonymous": anonymous}
        return user_id

    def count(self, kind: str) -> int:
        return self.calls.count(kind)

    def session_ids(self, email: str) -> list[str]:
        return [sid for sid, s in self.sessions.items() if s["email"] == email.lower()]

    # ------------------------------------------------------------------ tokens
    def _user_json(self, email: str) -> dict:
        user = self.users[email]
        return {"id": user["id"], "aud": "authenticated", "role": "authenticated", "email": email,
                "app_metadata": {"provider": "email"}, "user_metadata": {},
                "created_at": "2026-01-01T00:00:00Z", "is_anonymous": user["anonymous"]}

    def _new_session(self, email: str) -> dict:
        sid = str(uuid.uuid4())
        self.sessions[sid] = {"email": email, "revoked": False}
        return self._issue(sid)

    def _issue(self, sid: str) -> dict:
        email = self.sessions[sid]["email"]
        now = int(time.time())
        refresh = secrets.token_urlsafe(16)
        self.refresh_tokens[refresh] = {"sid": sid, "used": False}
        access = jwt.encode({"sub": self.users[email]["id"], "email": email, "role": "authenticated",
                             "aud": "authenticated", "iat": now, "exp": now + self.access_ttl, "session_id": sid,
                             "jti": secrets.token_hex(6)},
                            SECRET, "HS256")
        return {"access_token": access, "token_type": "bearer", "expires_in": max(self.access_ttl, 1),
                "expires_at": now + self.access_ttl, "refresh_token": refresh, "user": self._user_json(email)}

    # ------------------------------------------------------------------ the server
    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.fail_always is not None:
            if isinstance(self.fail_always, Exception):
                raise self.fail_always
            return self.fail_always
        path = request.url.path.removeprefix("/auth/v1")
        if path == "/token":
            grant = request.url.params.get("grant_type")
            body = json.loads(request.content or b"{}")
            return self._password(body) if grant == "password" else self._refresh(body) if grant == "refresh_token" \
                else gotrue_error(400, "unsupported_grant_type", "unsupported grant type")
        if path == "/user" and request.method == "GET":
            return self._user(request)
        if path == "/logout" and request.method == "POST":
            return self._logout(request)
        return gotrue_error(404, "not_found", f"unexpected request {request.method} {path}")

    def _password(self, body: dict) -> httpx.Response:
        self.calls.append("password")
        if self.rate_limited:
            return gotrue_error(429, "over_request_rate_limit", "Request rate limit reached")
        user = self.users.get(str(body.get("email", "")).lower())
        if user is None or user["password"] != body.get("password"):
            return gotrue_error(400, "invalid_credentials", "Invalid login credentials")
        return httpx.Response(200, json=self._new_session(str(body["email"]).lower()))

    def _refresh(self, body: dict) -> httpx.Response:
        self.calls.append("refresh")
        record = self.refresh_tokens.get(body.get("refresh_token", ""))
        if record is None:
            return gotrue_error(400, "refresh_token_not_found", "Invalid Refresh Token: Refresh Token Not Found")
        session = self.sessions[record["sid"]]
        if record["used"] or session["revoked"]:
            session["revoked"] = True                      # reuse ends the whole session
            return gotrue_error(400, "refresh_token_already_used", "Invalid Refresh Token: Already Used")
        record["used"] = True
        return httpx.Response(200, json=self._issue(record["sid"]))

    def _claims(self, request: httpx.Request):
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        try:
            return jwt.decode(token, SECRET, algorithms=["HS256"], audience="authenticated")
        except jwt.ExpiredSignatureError:
            return gotrue_error(401, "bad_jwt", "invalid JWT: token is expired")
        except jwt.PyJWTError:
            return gotrue_error(401, "bad_jwt", "invalid JWT: unable to parse or verify signature")

    def _user(self, request: httpx.Request) -> httpx.Response:
        self.calls.append("user")
        claims = self._claims(request)
        if isinstance(claims, httpx.Response):
            return claims
        session = self.sessions.get(claims["session_id"])
        if session is None or session["revoked"]:
            return gotrue_error(403, "session_not_found", "Session from session_id claim in JWT does not exist")
        return httpx.Response(200, json=self._user_json(claims["email"]))

    def _logout(self, request: httpx.Request) -> httpx.Response:
        self.calls.append("logout")
        claims = self._claims(request)
        if isinstance(claims, httpx.Response):
            return claims
        if request.url.params.get("scope") == "local" and claims["session_id"] in self.sessions:
            self.sessions[claims["session_id"]]["revoked"] = True
        return httpx.Response(204)


class FakeSupabase:
    """Auth and the REST API behind one HTTP client, like the real project URL."""

    def __init__(self) -> None:
        self.auth = FakeGoTrue()
        self.rest = FakePostgrest()
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.startswith("/auth/v1"):
            return self.auth.handle(request)
        if request.url.path.startswith("/rest/v1"):
            return self.rest.handle(request)
        return httpx.Response(404, json={"message": "not found"})

    def http_client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))
