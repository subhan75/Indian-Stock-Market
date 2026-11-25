"""Saved holdings and watched stocks: validation and storage (Phase 2 spec, section 4).

Validation messages are the exact sentences in the spec's error catalogue.
"""
import logging
import math
import re
import sqlite3
from datetime import datetime
from typing import Any

from . import config, report
from .db import connect
from .errors import ApiError
from .sources.prices import IST

log = logging.getLogger("stock_analyst.holdings")

SYMBOL_RE = re.compile(r"^[A-Za-z0-9&\-]{1,20}$")
GENERIC = "That request wasn't valid."
MSG_SYMBOL = "That doesn't look like an NSE symbol."
MSG_SHARES = "Enter the number of shares as a whole number, 1 or more."
MSG_SHARES_BIG = "That number of shares looks too large. Check it."
MSG_PRICE = "Enter your average buy price in rupees, more than 0."


def _bad(message: str) -> ApiError:
    return ApiError("bad_request", message)


def clean_symbol(raw: Any) -> str:
    if not isinstance(raw, str) or not SYMBOL_RE.match(raw.strip()):
        raise _bad(MSG_SYMBOL)
    return raw.strip().upper()


def parse_body(body: Any) -> dict:
    """Validate a HoldingIn body. `symbol` is None when the body omits it (allowed on PUT)."""
    if not isinstance(body, dict):
        raise _bad(GENERIC)
    watching = body.get("watching", False)
    if not isinstance(watching, bool):
        raise _bad(GENERIC)
    symbol = clean_symbol(body["symbol"]) if body.get("symbol") is not None else None
    if watching:
        return {"symbol": symbol, "watching": True, "shares": None, "buy_price": None}

    shares = body.get("shares")
    if isinstance(shares, bool) or not isinstance(shares, int) or shares < 1:
        raise _bad(MSG_SHARES)
    if shares > config.MAX_SHARES:
        raise _bad(MSG_SHARES_BIG)

    price = body.get("buy_price")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price):
        raise _bad(MSG_PRICE)
    price = round(float(price), 2)
    if price <= 0 or price > config.MAX_BUY_PRICE:
        raise _bad(MSG_PRICE)
    return {"symbol": symbol, "watching": False, "shares": shares, "buy_price": price}


# ----------------------------------------------------------------------------- storage
def _saved(row) -> dict:
    return {"symbol": row["symbol"], "name": row["name"] or row["symbol"], "watching": bool(row["watching"]),
            "shares": row["shares"], "buy_price": row["buy_price"], "added_at": row["added_at"]}


_SELECT = ("SELECT h.symbol, h.shares, h.buy_price, h.watching, h.added_at, c.name AS name "
           "FROM holdings h LEFT JOIN companies c ON c.symbol = h.symbol")


def list_holdings() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(_SELECT + " ORDER BY h.added_at, h.rowid").fetchall()
    return [_saved(r) for r in rows]


def get_holding(symbol: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(_SELECT + " WHERE h.symbol = ?", (symbol,)).fetchone()
    return _saved(row) if row else None


def create(body: Any) -> dict:
    data = parse_body(body)
    if data["symbol"] is None:
        raise _bad(MSG_SYMBOL)
    symbol = data["symbol"]
    report.resolve_company(symbol)  # 404 if it isn't on the NSE list
    if get_holding(symbol):
        raise _bad(f"You already have {symbol}. Edit it instead.")
    if len(list_holdings()) >= config.MAX_HOLDINGS:
        raise _bad(f"You can keep up to {config.MAX_HOLDINGS} stocks in v0.")
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO holdings (symbol, shares, buy_price, watching, added_at) VALUES (?,?,?,?,?)",
                (symbol, data["shares"], data["buy_price"], int(data["watching"]),
                 datetime.now(IST).isoformat(timespec="seconds")),
            )
    except sqlite3.IntegrityError:  # two requests raced
        raise _bad(f"You already have {symbol}. Edit it instead.")
    return get_holding(symbol)


def update(path_symbol: str, body: Any) -> dict:
    symbol = clean_symbol(path_symbol)
    if get_holding(symbol) is None:
        raise ApiError("not_found", f"{symbol} isn't in your stocks.")
    data = parse_body(body)
    if data["symbol"] is not None and data["symbol"] != symbol:
        raise _bad("The symbol in the form doesn't match the stock being edited.")
    with connect() as conn:
        conn.execute("UPDATE holdings SET shares = ?, buy_price = ?, watching = ? WHERE symbol = ?",
                     (data["shares"], data["buy_price"], int(data["watching"]), symbol))
    return get_holding(symbol)


def delete(path_symbol: str) -> dict:
    symbol = clean_symbol(path_symbol)
    with connect() as conn:
        removed = conn.execute("DELETE FROM holdings WHERE symbol = ?", (symbol,)).rowcount
    if not removed:
        raise ApiError("not_found", f"{symbol} isn't in your stocks.")
    return {"deleted": True}


def ensure_report(symbol: str) -> None:
    """Best effort: give a new row its Phase 1 report. A failure here never fails the save."""
    try:
        report.get_report(symbol)
    except Exception as exc:
        log.warning("Couldn't build the first report for %s: %s", symbol, exc)
