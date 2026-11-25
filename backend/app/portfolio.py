"""The My stocks view: holdings joined with cached reports, live prices and flags.

Reads cached reports only. It never calls Screener, so opening the page is fast and polite.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable

from . import flags, holdings, report
from .format import percent_direction, rupees, rupees_auto, signed_rupees
from .sources import prices
from .sources.prices import IST, format_time

log = logging.getLogger("stock_analyst.portfolio")
NO_PRICE = "Price unavailable"
MAX_PRICE_WORKERS = 8


def live_price(symbol: str) -> float | None:
    """Today's price from Yahoo Finance, or None. Never raises."""
    try:
        result = prices.fetch_price(symbol)
        return result.price if result.ok and result.source == "Yahoo Finance" else None
    except Exception as exc:
        log.warning("Live price for %s failed: %s", symbol, exc)
        return None


def _live_prices(symbols: list[str], price_fn: Callable[[str], float | None]) -> dict[str, float | None]:
    if not symbols:
        return {}

    def safe(symbol: str):
        try:
            return price_fn(symbol)
        except Exception as exc:
            log.warning("Live price for %s failed: %s", symbol, exc)
            return None

    with ThreadPoolExecutor(max_workers=min(MAX_PRICE_WORKERS, len(symbols))) as pool:
        return dict(zip(symbols, pool.map(safe, symbols)))


def _updated_display(latest: dict | None) -> str | None:
    if not latest:
        return None
    try:
        d = datetime.fromisoformat(latest["generated_at"]).astimezone(IST)
    except (KeyError, ValueError):
        return None
    return f"{d.day} {d:%b}"


def _excluded_note(count: int) -> str | None:
    if count == 0:
        return None
    if count == 1:
        return "1 stock isn't included because its price couldn't be fetched."
    return f"{count} stocks aren't included because their prices couldn't be fetched."


def build(price_fn: Callable[[str], float | None] | None = None, now: datetime | None = None) -> dict:
    price_fn = price_fn or live_price
    saved = holdings.list_holdings()
    reports = {h["symbol"]: report.recent_reports(h["symbol"], 2) for h in saved}
    live = _live_prices([h["symbol"] for h in saved], price_fn)

    rows = []
    invested_total = value_total = 0.0
    excluded = 0
    for h in saved:
        symbol, watching = h["symbol"], h["watching"]
        found = reports[symbol]
        latest = found[0] if found else None
        previous = found[1] if len(found) > 1 else None

        price, source = live.get(symbol), "live"
        if price is None:
            price, source = flags.report_price(latest), "report"
        if price is None:
            source = None

        row = {
            "symbol": symbol, "name": h["name"], "watching": watching,
            "shares": h["shares"], "buy_price": h["buy_price"],
            "buy_price_display": rupees_auto(h["buy_price"]) if h["buy_price"] is not None else None,
            "price_display": rupees_auto(price) if price is not None else NO_PRICE,
            "price_source": source,
            "value_display": None, "gain_display": None, "direction": None,
            "has_report": latest is not None,
            "label": latest["label"] if latest else None,
            "flag": flags.flag_block(flags.evaluate(watching=watching, buy_price=h["buy_price"], price=price,
                                                    latest=latest, previous=previous)),
            "report_updated_display": _updated_display(latest),
            "report_url": f"/report.html?symbol={symbol}",
        }
        value = None
        if not watching:
            if price is None:
                excluded += 1
            else:
                invested = h["shares"] * h["buy_price"]
                value = h["shares"] * price
                gain = value - invested
                pct = gain / invested * 100
                row["value_display"] = rupees(value)
                row["gain_display"] = signed_rupees(gain, pct)
                row["direction"] = percent_direction(pct)
                invested_total += invested
                value_total += value
        row["_sort"] = (1 if watching else 0, 0 if row["flag"]["on"] else 1,
                        -(value if value is not None else -1.0), h["name"].lower() if watching else symbol)
        rows.append(row)

    rows.sort(key=lambda r: r["_sort"])
    for r in rows:
        del r["_sort"]

    gain_total = value_total - invested_total
    pct_total = gain_total / invested_total * 100 if invested_total else 0.0
    return {
        "as_of": format_time(now or datetime.now(IST)),
        "totals": {
            "invested_display": rupees(invested_total),
            "value_display": rupees(value_total),
            "gain_display": signed_rupees(gain_total, pct_total),
            "direction": percent_direction(pct_total),
            "excluded": excluded,
            "note": _excluded_note(excluded),
        },
        "rows": rows,
    }
