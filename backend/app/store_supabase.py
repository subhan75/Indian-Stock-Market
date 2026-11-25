"""The Supabase implementation of the per-user store.

Every call goes to Supabase's REST API (PostgREST) carrying the SIGNED-IN USER'S OWN access token, with the
publishable key as the API key. Postgres Row Level Security therefore decides which rows are visible, and a bug
in this code cannot reach another user's data. There is no secret / service-role key anywhere in this project.

A client is created per request (cheap, because they all share one connection pool) so no user's session can
ever be held by, or leaked through, a shared client.
"""
import threading
from typing import Any, Callable

import httpx
from postgrest.exceptions import APIError
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

from . import config
from .store import REPORTS_KEPT_PER_STOCK, Conflict, NotAuthorized, StoreError

UNIQUE_VIOLATION = "23505"
INSUFFICIENT_PRIVILEGE = "42501"

_pool_lock = threading.Lock()
_shared_http: httpx.Client | None = None


def shared_http() -> httpx.Client:
    """One connection pool for every request, so we don't pay a TLS handshake each time."""
    global _shared_http
    with _pool_lock:
        if _shared_http is None:
            _shared_http = httpx.Client(timeout=config.DB_TIMEOUT_SECONDS,
                                        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10))
        return _shared_http


def configured() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_PUBLISHABLE_KEY)


def make_client(access_token: str | None = None, http: httpx.Client | None = None) -> Client:
    """A fresh, stateless client. With a token, requests act as that user; without one, as the anonymous role
    (which the schema grants nothing to)."""
    if not configured():
        raise StoreError("Supabase isn't configured (SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY).")
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    options = SyncClientOptions(headers=headers, auto_refresh_token=False, persist_session=False,
                                postgrest_client_timeout=config.DB_TIMEOUT_SECONDS,
                                postgrest_client_retry=config.DB_RETRY_READS,
                                httpx_client=http or shared_http())
    return create_client(config.SUPABASE_URL, config.SUPABASE_PUBLISHABLE_KEY, options)


def _translate(exc: Exception) -> Exception:
    """Turn a library error into one of ours."""
    if isinstance(exc, APIError):
        code = exc.code or ""
        if code == UNIQUE_VIOLATION:
            return Conflict(exc.message or "duplicate")
        if code.startswith("PGRST3") or "jwt" in (exc.message or "").lower():
            return NotAuthorized(exc.message or "The session has expired.")
        if code == INSUFFICIENT_PRIVILEGE:
            return StoreError("The database refused access (missing grant or policy). Run supabase/schema.sql.")
        return StoreError(f"The database returned an error ({code or 'unknown'}).")
    if isinstance(exc, (httpx.HTTPError, OSError)):
        return StoreError("The database isn't reachable.")
    return exc


def _run(call: Callable[[], Any]) -> Any:
    try:
        return call().data
    except Exception as exc:  # noqa: BLE001 - translated or re-raised just below
        translated = _translate(exc)
        if translated is exc:
            raise
        raise translated from exc


class SupabaseStore:
    """One signed-in user's holdings and reports, read and written through Row Level Security."""

    def __init__(self, client: Client, user_id: str) -> None:
        self._db = client
        self._user = user_id
        self.user_id = user_id

    # ------------------------------------------------------------------ holdings
    _HOLDING_COLUMNS = "symbol,shares,buy_price,watching,added_at"

    def _holdings(self):
        return self._db.table("holdings")

    def holdings_list(self) -> list[dict]:
        return _run(lambda: self._holdings().select(self._HOLDING_COLUMNS)
                    .eq("user_id", self._user).order("id").execute()) or []

    def holdings_get(self, symbol: str) -> dict | None:
        rows = _run(lambda: self._holdings().select(self._HOLDING_COLUMNS)
                    .eq("user_id", self._user).eq("symbol", symbol.upper()).limit(1).execute())
        return rows[0] if rows else None

    def holdings_insert(self, row: dict) -> None:
        _run(lambda: self._holdings().insert({
            "user_id": self._user, "symbol": row["symbol"].upper(), "shares": row["shares"],
            "buy_price": row["buy_price"], "watching": bool(row["watching"]), "added_at": row["added_at"],
        }).execute())

    def holdings_update(self, symbol: str, shares: int | None, buy_price: float | None, watching: bool) -> bool:
        rows = _run(lambda: self._holdings().update(
            {"shares": shares, "buy_price": buy_price, "watching": bool(watching)})
            .eq("user_id", self._user).eq("symbol", symbol.upper()).execute())
        return bool(rows)

    def holdings_delete(self, symbol: str) -> bool:
        rows = _run(lambda: self._holdings().delete()
                    .eq("user_id", self._user).eq("symbol", symbol.upper()).execute())
        return bool(rows)

    # ------------------------------------------------------------------ reports
    def _reports(self):
        return self._db.table("reports")

    def reports_save(self, report: dict) -> None:
        symbol = report["symbol"].upper()
        _run(lambda: self._reports().upsert(
            {"user_id": self._user, "symbol": symbol, "generated_at": report["generated_at"],
             "label": report["label"]["code"], "report_json": report},
            on_conflict="user_id,symbol,generated_at").execute())
        # Keep only the newest few per stock: one cheap query, and a delete only when something is over the limit.
        stale = _run(lambda: self._reports().select("generated_at")
                     .eq("user_id", self._user).eq("symbol", symbol)
                     .order("generated_at", desc=True)
                     .range(REPORTS_KEPT_PER_STOCK, REPORTS_KEPT_PER_STOCK + 99).execute()) or []
        if stale:
            _run(lambda: self._reports().delete().eq("user_id", self._user).eq("symbol", symbol)
                 .in_("generated_at", [r["generated_at"] for r in stale]).execute())

    def reports_recent(self, symbol: str, n: int) -> list[dict]:
        rows = _run(lambda: self._reports().select("report_json")
                    .eq("user_id", self._user).eq("symbol", symbol.upper())
                    .order("generated_at", desc=True).limit(n).execute()) or []
        return [r["report_json"] for r in rows]

    def reports_latest_by_symbol(self, limit: int) -> list[dict]:
        # PostgREST has no "newest per group", so read the newest rows (three small columns) and keep the first
        # row seen for each stock. A user has at most 100 stocks x 10 reports, within one 1,000-row response.
        rows = _run(lambda: self._reports().select("symbol,label,generated_at")
                    .eq("user_id", self._user).order("generated_at", desc=True).limit(500).execute()) or []
        seen: dict[str, dict] = {}
        for r in rows:
            seen.setdefault(r["symbol"], {"symbol": r["symbol"], "label": r["label"],
                                          "generated_at": r["generated_at"]})
        return list(seen.values())[:limit]
