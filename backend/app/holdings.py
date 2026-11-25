"""Saved holdings and watched stocks: validation and storage (Phase 2 spec, section 4).

Validation messages are the exact sentences in the spec's error catalogue.
"""
import logging
import math
import re
from datetime import datetime
from typing import Any

from . import config, report, store
from .errors import ApiError
from .sources import nse
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
def _saved(row: dict) -> dict:
    company = nse.get_company(row["symbol"])
    return {"symbol": row["symbol"], "name": company["name"] if company else row["symbol"],
            "watching": bool(row["watching"]), "shares": row["shares"], "buy_price": row["buy_price"],
            "added_at": row["added_at"]}


def list_holdings() -> list[dict]:
    nse.ensure_loaded()                      # names come from the company list
    return [_saved(r) for r in store.current().holdings_list()]


def get_holding(symbol: str) -> dict | None:
    nse.ensure_loaded()
    row = store.current().holdings_get(symbol)
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
        store.current().holdings_insert({
            "symbol": symbol, "shares": data["shares"], "buy_price": data["buy_price"],
            "watching": data["watching"], "added_at": datetime.now(IST).isoformat(timespec="seconds")})
    except store.Conflict:  # two requests raced
        raise _bad(f"You already have {symbol}. Edit it instead.")
    return get_holding(symbol)


def update(path_symbol: str, body: Any) -> dict:
    symbol = clean_symbol(path_symbol)
    if get_holding(symbol) is None:
        raise ApiError("not_found", f"{symbol} isn't in your stocks.")
    data = parse_body(body)
    if data["symbol"] is not None and data["symbol"] != symbol:
        raise _bad("The symbol in the form doesn't match the stock being edited.")
    store.current().holdings_update(symbol, data["shares"], data["buy_price"], data["watching"])
    return get_holding(symbol)


def delete(path_symbol: str) -> dict:
    symbol = clean_symbol(path_symbol)
    if not store.current().holdings_delete(symbol):
        raise ApiError("not_found", f"{symbol} isn't in your stocks.")
    return {"deleted": True}


def ensure_report(symbol: str) -> None:
    """Best effort: give a new row its Phase 1 report. A failure here never fails the save."""
    try:
        report.get_report(symbol)
    except Exception as exc:
        log.warning("Couldn't build the first report for %s: %s", symbol, exc)
