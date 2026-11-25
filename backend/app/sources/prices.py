"""Latest price and today's change: yfinance first, Screener's price as the fallback."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from ..format import rupees_auto

IST = timezone(timedelta(hours=5, minutes=30))
YF_TIMEOUT_SECONDS = 15


@dataclass
class PriceResult:
    ok: bool
    price: float | None = None
    change_pct: float | None = None
    source: str = ""          # "Yahoo Finance" | "Screener.in"
    source_url: str = ""
    fetched_at: datetime | None = None
    note: str = ""            # plain-words reason when not ok


def _yf_quote(ticker: str) -> tuple[float, float | None]:
    """(last price, previous close) for any Yahoo ticker, e.g. 'ABB.NS' or '^NSEI'."""
    import yfinance as yf  # imported lazily: it is slow to import and not needed by every test

    info = yf.Ticker(ticker).fast_info
    last = info["last_price"]
    prev = info["previous_close"]
    if last is None or last != last:  # None or NaN
        raise ValueError("no price")
    return float(last), (float(prev) if prev else None)


def _yf_fetch(symbol: str) -> tuple[float, float | None]:
    return _yf_quote(f"{symbol}.NS")


def fetch_price(symbol: str, fallback_price: float | None = None, fallback_url: str = "",
                yf_fetch: Callable[[str], tuple[float, float | None]] = _yf_fetch) -> PriceResult:
    now = datetime.now(IST)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        last, prev = pool.submit(yf_fetch, symbol).result(timeout=YF_TIMEOUT_SECONDS)
        change = round((last / prev - 1) * 100, 2) if prev else None
        return PriceResult(True, last, change, "Yahoo Finance",
                           f"https://finance.yahoo.com/quote/{symbol}.NS/", now)
    except (Exception, FutureTimeout):  # yfinance raises many unrelated types; any failure falls back
        if fallback_price is not None:
            return PriceResult(True, fallback_price, None, "Screener.in", fallback_url, now,
                               "Today's change isn't available right now.")
        return PriceResult(False, note="Couldn't fetch the price right now.", fetched_at=now)
    finally:
        pool.shutdown(wait=False)


def format_time(dt: datetime) -> str:
    """'25 Nov, 3:30 pm' in Indian time."""
    dt = dt.astimezone(IST)
    hour = dt.hour % 12 or 12
    return f"{dt.day} {dt:%b}, {hour}:{dt:%M} {'am' if dt.hour < 12 else 'pm'}"


def format_clock(dt: datetime, now: datetime) -> str:
    """'2:10 pm' for a time on the same India-time date as `now`, else '24 Nov, 9:05 pm'."""
    d, n = dt.astimezone(IST), now.astimezone(IST)
    hour = d.hour % 12 or 12
    clock = f"{hour}:{d:%M} {'am' if d.hour < 12 else 'pm'}"
    return clock if d.date() == n.date() else f"{d.day} {d:%b}, {clock}"


def price_block(result: PriceResult) -> dict:
    """The `price` object of the Report contract, ready to display."""
    if not result.ok or result.price is None:
        return {"display": "Price unavailable", "change_display": "", "direction": "flat",
                "as_of": format_time(result.fetched_at) if result.fetched_at else "", "value": None}
    price = result.price
    display = rupees_auto(price)
    if result.change_pct is None:
        change, direction = "", "flat"
    else:
        direction = "up" if result.change_pct > 0 else "down" if result.change_pct < 0 else "flat"
        change = f"{result.change_pct:+.1f}%"
    return {"display": display, "change_display": change, "direction": direction,
            "as_of": format_time(result.fetched_at), "value": float(price)}
