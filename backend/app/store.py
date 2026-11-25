"""Per-user storage for holdings and reports.

`Store` is the one place the app reads and writes saved data. There are two implementations:
- `store_supabase.SupabaseStore`: production. Every call carries the signed-in user's own token, so Postgres
  Row Level Security decides which rows are visible. There is no secret key anywhere in this project.
- `InMemoryStore`: tests and offline development.

A store belongs to ONE signed-in user. The request guard sets it for the duration of a request with `use()`, and
modules ask for it with `current()`, so function signatures elsewhere stay unchanged. Code that starts its own
threads must not use the store from them (contextvars are not inherited by new threads).
"""
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Protocol

REPORTS_KEPT_PER_STOCK = 10     # flags only compare the two newest; keep a few more for context


class StoreError(Exception):
    """The database couldn't be reached or answered unexpectedly. The API turns this into a 503."""


class Conflict(Exception):
    """A unique constraint was violated (for example the same stock saved twice)."""


class NoStore(RuntimeError):
    """Code tried to use saved data outside of a signed-in request. A bug, never a user error."""


class Store(Protocol):
    # holdings: {"symbol","shares","buy_price","watching","added_at"}, oldest first
    def holdings_list(self) -> list[dict]: ...
    def holdings_get(self, symbol: str) -> dict | None: ...
    def holdings_insert(self, row: dict) -> None: ...                       # raises Conflict
    def holdings_update(self, symbol: str, shares: int | None, buy_price: float | None, watching: bool) -> bool: ...
    def holdings_delete(self, symbol: str) -> bool: ...
    # reports: full report dicts
    def reports_save(self, report: dict) -> None: ...
    def reports_recent(self, symbol: str, n: int) -> list[dict]: ...        # newest first
    def reports_latest_by_symbol(self, limit: int) -> list[dict]: ...       # [{"symbol","label","generated_at"}]


# ----------------------------------------------------------------------------- who is the current store?
_current: ContextVar["Store | None"] = ContextVar("stock_analyst_store", default=None)
_test_fallback: "Store | None" = None


def current() -> Store:
    found = _current.get() or _test_fallback
    if found is None:
        raise NoStore("No signed-in user is attached to this request.")
    return found


@contextmanager
def use(store: Store) -> Iterator[Store]:
    token = _current.set(store)
    try:
        yield store
    finally:
        _current.reset(token)


def bind(store: Store):
    """Attach `store` to the current context and return a token for `unbind`. Used by the request guard."""
    return _current.set(store)


def unbind(token) -> None:
    _current.reset(token)


def install_test_store(store: "Store | None") -> None:
    """Tests only: make `store` visible from every thread (the test client runs the app in another thread).
    Refuses to run outside pytest so production can never end up with a shared, user-less store."""
    global _test_fallback
    if store is not None and "PYTEST_CURRENT_TEST" not in os.environ:
        raise RuntimeError("install_test_store is for tests only")
    _test_fallback = store


# ----------------------------------------------------------------------------- in-memory implementation
class InMemoryStore:
    """Behaves like the Supabase store for one user, including the unique constraint and newest-N pruning."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._holdings: list[dict] = []
        self._reports: dict[tuple[str, str], dict] = {}     # (SYMBOL, generated_at) -> report

    # holdings
    def holdings_list(self) -> list[dict]:
        with self._lock:
            return [dict(h) for h in self._holdings]

    def holdings_get(self, symbol: str) -> dict | None:
        with self._lock:
            found = next((h for h in self._holdings if h["symbol"] == symbol.upper()), None)
            return dict(found) if found else None

    def holdings_insert(self, row: dict) -> None:
        symbol = row["symbol"].upper()
        with self._lock:
            if any(h["symbol"] == symbol for h in self._holdings):
                raise Conflict(symbol)
            self._holdings.append({"symbol": symbol, "shares": row["shares"], "buy_price": row["buy_price"],
                                   "watching": bool(row["watching"]), "added_at": row["added_at"]})

    def holdings_update(self, symbol: str, shares: int | None, buy_price: float | None, watching: bool) -> bool:
        with self._lock:
            for h in self._holdings:
                if h["symbol"] == symbol.upper():
                    h.update(shares=shares, buy_price=buy_price, watching=bool(watching))
                    return True
        return False

    def holdings_delete(self, symbol: str) -> bool:
        with self._lock:
            before = len(self._holdings)
            self._holdings = [h for h in self._holdings if h["symbol"] != symbol.upper()]
            return len(self._holdings) < before

    # reports
    def reports_save(self, report: dict[str, Any]) -> None:
        symbol = report["symbol"].upper()
        with self._lock:
            self._reports[(symbol, report["generated_at"])] = dict(report)       # same key replaces, as before
            mine = sorted((k for k in self._reports if k[0] == symbol), key=lambda k: k[1], reverse=True)
            for stale in mine[REPORTS_KEPT_PER_STOCK:]:
                del self._reports[stale]

    def reports_recent(self, symbol: str, n: int) -> list[dict]:
        with self._lock:
            keys = sorted((k for k in self._reports if k[0] == symbol.upper()), key=lambda k: k[1], reverse=True)
            return [dict(self._reports[k]) for k in keys[:n]]

    def reports_latest_by_symbol(self, limit: int) -> list[dict]:
        with self._lock:
            newest: dict[str, dict] = {}
            for (symbol, generated_at), report in self._reports.items():
                if symbol not in newest or generated_at > newest[symbol]["generated_at"]:
                    newest[symbol] = {"symbol": symbol, "label": report["label"]["code"], "generated_at": generated_at}
            return sorted(newest.values(), key=lambda r: r["generated_at"], reverse=True)[:limit]
