"""Screener.in company page: fetch (cached 24h, throttled) and parse into plain numbers.

Layout facts verified against live pages (Nov 2026):
- Top ratios, about text, quarters, balance sheet and the peers table are all in the one HTML page.
  There is no separate peers request.
- The peers table has sector-specific columns (banks, telecom...), so P/E is found by header text.
- Screener's own "Median: N Co." row includes the company itself, so we compute our own median
  over the *other* peers.
- Banks label sales "Revenue" and borrowings "Borrowing", and have a "Deposits" row.
"""
import re
import statistics
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from .. import config
from ..db import connect
from .base import NotFound, SourceUnavailable

BASE = "https://www.screener.in"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockAnalystV0/0.1; personal research tool)"}
NOT_FOUND_SENTINEL = "__NOT_FOUND__"
SYMBOL_RE = re.compile(r"^[A-Za-z0-9&\-]{1,20}$")
_NUM = re.compile(r"-?\d[\d,]*\.?\d*|-?\.\d+")


# ----------------------------------------------------------------------------- data shapes
@dataclass
class Peer:
    symbol: str
    name: str
    pe: float | None


@dataclass
class ScreenerData:
    symbol: str
    url: str
    fetched_at: str
    consolidated: bool
    name: str = ""
    about: str = ""
    price: float | None = None
    pe: float | None = None
    roce: float | None = None
    industry: str = ""
    broad_industry: str = ""
    quarter_labels: list[str] = field(default_factory=list)   # last 8, oldest first
    sales: list[float | None] = field(default_factory=list)    # aligned with quarter_labels
    net_profit: list[float | None] = field(default_factory=list)
    opm: float | None = None                                   # latest quarter, %
    equity_capital: float | None = None
    reserves: float | None = None
    borrowings: float | None = None
    balance_as_of: str = ""
    has_deposits: bool = False
    peers: list[Peer] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        """False for empty shells (e.g. delisted or data-less pages)."""
        return self.price is not None or self.pe is not None or bool(self.sales)

    @property
    def peer_pes(self) -> list[float]:
        return [p.pe for p in self.peers if p.pe is not None and p.pe > 0]

    @property
    def median_peer_pe(self) -> float | None:
        pes = self.peer_pes
        return statistics.median(pes) if len(pes) >= config.MIN_PEERS else None


# ----------------------------------------------------------------------------- parsing helpers
def to_number(text: str | None) -> float | None:
    if not text:
        return None
    m = _NUM.search(text.replace("−", "-"))
    return float(m.group().replace(",", "")) if m else None


def _clean(text: str) -> str:
    return " ".join(text.split())


def _cells(tr):
    return tr.find_all(["th", "td"], recursive=False)


def _table_rows(table) -> tuple[list[str], dict[str, list[str]]]:
    """Return (column labels, {row label lowercased: values}) for a Screener data table."""
    labels: list[str] = []
    rows: dict[str, list[str]] = {}
    for tr in table.select("tr"):
        cells = [_clean(c.get_text(" ")) for c in _cells(tr)]
        if not cells:
            continue
        if not labels and tr.find("th") and not tr.find("td"):
            labels = cells[1:]
            continue
        rows.setdefault(cells[0].lower(), cells[1:])
    return labels, rows


def _find_row(rows: dict[str, list[str]], *prefixes: str) -> list[str] | None:
    for label, values in rows.items():
        if label.startswith(prefixes):
            return values
    return None


def _numbers(values: list[str] | None, n: int) -> list[float | None]:
    return [to_number(v) for v in (values or [])][-n:]


def _top_ratios(soup) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for li in soup.select("#top-ratios li"):
        name = li.select_one(".name")
        number = li.select_one(".value .number")
        if name:
            out[_clean(name.get_text()).lower()] = to_number(number.get_text()) if number else None
    return out


def _parse_peers(soup, own_symbol: str) -> list[Peer]:
    table = soup.select_one("#peers table")
    if table is None:
        return []
    pe_col = None
    peers: list[Peer] = []
    for tr in table.select("tr"):
        cells = _cells(tr)
        texts = [_clean(c.get_text(" ")) for c in cells]
        if pe_col is None:
            if any(t.startswith("Company") for t in texts):
                for i, t in enumerate(texts):
                    if t.startswith("P/E"):
                        pe_col = i
                        break
            continue
        link = tr.find("a", href=re.compile(r"^/company/"))
        if link is None or len(cells) <= pe_col:
            continue  # "Median" row, "Key insights" row, etc.
        m = re.match(r"^/company/([^/]+)/", link["href"])
        symbol = m.group(1) if m else ""
        if symbol.upper() == own_symbol.upper():
            continue
        peers.append(Peer(symbol=symbol, name=_clean(link.get_text()), pe=to_number(texts[pe_col])))
    return peers


def parse_company_page(html: str, symbol: str, url: str, fetched_at: str) -> ScreenerData:
    soup = BeautifulSoup(html, "lxml")
    consolidated = "/consolidated/" in url
    data = ScreenerData(symbol=symbol, url=url, fetched_at=fetched_at, consolidated=consolidated)

    h1 = soup.select_one("h1")
    data.name = _clean(h1.get_text(" ")) if h1 else ""

    about = soup.select_one(".company-profile .about") or soup.select_one(".about")
    if about:
        for sup in about.select("sup"):
            sup.decompose()
        data.about = _clean(about.get_text(" "))

    ratios = _top_ratios(soup)
    data.price = ratios.get("current price")
    data.pe = ratios.get("stock p/e")
    data.roce = ratios.get("roce")

    industries = {a.get("title", ""): _clean(a.get_text()) for a in soup.select("#peers p.sub a")}
    data.broad_industry = industries.get("Broad Industry", "")
    data.industry = industries.get("Industry", "")

    q = soup.select_one("#quarters table")
    if q is not None:
        labels, rows = _table_rows(q)
        data.quarter_labels = labels[-8:]
        data.sales = _numbers(_find_row(rows, "sales", "revenue"), 8)
        data.net_profit = _numbers(_find_row(rows, "net profit"), 8)
        opm = _numbers(_find_row(rows, "opm", "financing margin"), 1)
        data.opm = opm[0] if opm else None

    bs = soup.select_one("#balance-sheet table")
    if bs is not None:
        labels, rows = _table_rows(bs)
        data.balance_as_of = labels[-1] if labels else ""
        for attr, prefixes in (("equity_capital", ("equity capital",)),
                               ("reserves", ("reserves",)),
                               ("borrowings", ("borrowing",))):
            vals = _numbers(_find_row(rows, *prefixes), 1)
            setattr(data, attr, vals[0] if vals else None)
        data.has_deposits = _find_row(rows, "deposits") is not None

    data.peers = _parse_peers(soup, symbol)
    return data


# ----------------------------------------------------------------------------- fetching
_throttle_lock = threading.Lock()
_last_request = 0.0


def _http_get(url: str) -> requests.Response:
    """One polite GET: at least SCREENER_MIN_GAP_SECONDS after the previous Screener request."""
    global _last_request
    with _throttle_lock:
        wait = config.SCREENER_MIN_GAP_SECONDS - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            return requests.get(url, headers=HEADERS, timeout=30)
        finally:
            _last_request = time.monotonic()


def _cache_get(url: str, ttl: timedelta) -> tuple[str, str] | None:
    with connect() as conn:
        row = conn.execute("SELECT body, fetched_at FROM page_cache WHERE url = ?", (url,)).fetchone()
    if row and datetime.now(timezone.utc) - datetime.fromisoformat(row["fetched_at"]) < ttl:
        return row["body"], row["fetched_at"]
    return None


def _cache_put(url: str, body: str) -> str:
    stamp = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        conn.execute(
            "INSERT INTO page_cache (url, body, fetched_at) VALUES (?,?,?) "
            "ON CONFLICT(url) DO UPDATE SET body=excluded.body, fetched_at=excluded.fetched_at",
            (url, body, stamp),
        )
    return stamp


def _get_cached(url: str, refresh: bool, http_get: Callable[[str], requests.Response]) -> tuple[str, str] | None:
    """Return (html, fetched_at), or None if the page doesn't exist (404)."""
    ttl = timedelta(hours=config.CACHE_TTL_HOURS)
    if not refresh:
        hit = _cache_get(url, ttl)
        if hit:
            return None if hit[0] == NOT_FOUND_SENTINEL else hit
    try:
        resp = http_get(url)
    except requests.RequestException as exc:
        raise SourceUnavailable("Couldn't reach Screener.in right now.") from exc
    if resp.status_code == 404:
        _cache_put(url, NOT_FOUND_SENTINEL)
        return None
    if resp.status_code != 200:
        raise SourceUnavailable(f"Screener.in answered with an error ({resp.status_code}).")
    return resp.text, _cache_put(url, resp.text)


def fetch_company(symbol: str, refresh: bool = False,
                  http_get: Callable[[str], requests.Response] = _http_get) -> ScreenerData:
    """Fetch and parse a stock's Screener page: consolidated first, standalone if there isn't one."""
    if not SYMBOL_RE.match(symbol):
        raise NotFound("That doesn't look like an NSE symbol.")
    slug = quote(symbol.upper(), safe="")
    for suffix in ("consolidated/", ""):
        url = f"{BASE}/company/{slug}/{suffix}"
        got = _get_cached(url, refresh, http_get)
        if got:
            html, fetched_at = got
            return parse_company_page(html, symbol.upper(), url, fetched_at)
    raise NotFound(f"Screener.in has no page for {symbol.upper()}.")
