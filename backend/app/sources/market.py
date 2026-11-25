"""Phase 3 sources: Nifty 50 / Sensex from yfinance, and the ET Markets and Business Standard RSS feeds."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import requests

from ..format import indian_int
from . import news, prices

INDICES = [
    ("Nifty 50", "^NSEI", "https://finance.yahoo.com/quote/%5ENSEI/"),
    ("Sensex", "^BSESN", "https://finance.yahoo.com/quote/%5EBSESN/"),
]
FEEDS = [
    ("ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Business Standard", "https://www.business-standard.com/rss/markets-106.rss"),
]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockAnalystV0/0.1; personal research tool)"}
INDEX_TIMEOUT_SECONDS = 15


@dataclass
class IndexResult:
    name: str
    url: str
    ok: bool
    level: float | None = None
    change_pct: float | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class FeedResult:
    name: str
    ok: bool
    headlines: list[news.Headline]
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def fetch_index(name: str, ticker: str, url: str,
                quote: Callable[[str], tuple[float, float | None]] = prices._yf_quote,
                timeout: float = INDEX_TIMEOUT_SECONDS) -> IndexResult:
    """Latest level and change vs the previous close. Never raises: a failure is ok=False."""
    pool = ThreadPoolExecutor(max_workers=1)
    now = datetime.now(timezone.utc)
    try:
        last, prev = pool.submit(quote, ticker).result(timeout=timeout)
        change = round((last / prev - 1) * 100, 2) if prev else None
        return IndexResult(name, url, True, float(last), change, now)
    except (Exception, FutureTimeout):  # yfinance raises many unrelated types
        return IndexResult(name, url, False, fetched_at=now)
    finally:
        pool.shutdown(wait=False)


def index_block(r: IndexResult) -> dict:
    """The `indices[]` entry of the MarketToday contract."""
    pct = r.change_pct
    direction = "flat" if pct is None else "up" if round(pct, 1) > 0 else "down" if round(pct, 1) < 0 else "flat"
    return {"name": r.name, "value_display": indian_int(r.level),
            "change_display": "" if pct is None else f"{pct:+.1f}%", "direction": direction,
            "source": "Yahoo Finance", "url": r.url}


def _http_get(url: str) -> requests.Response:
    return requests.get(url, headers=HEADERS, timeout=20)


def fetch_feed(name: str, url: str, http_get: Callable[[str], requests.Response] = _http_get,
               now: datetime | None = None, window_hours: int = 24) -> FeedResult:
    """One outlet's feed, last `window_hours`. Never raises."""
    fetched = datetime.now(timezone.utc)
    try:
        resp = http_get(url)
        if resp.status_code != 200:
            return FeedResult(name, False, [], fetched)
        return FeedResult(name, True, news.parse_plain_feed(resp.content, name, now, window_hours), fetched)
    except Exception:  # network errors, malformed feeds: this source is simply unavailable
        return FeedResult(name, False, [], fetched)
