"""NSE equity list: kept in the backend's memory, refreshed weekly, searched in Python.

The list is public data, so it lives in memory rather than in the database (the backend has no secret key and so
cannot safely write shared tables). If the download is blocked or fails and nothing is loaded, a bundled snapshot
(`backend/data/EQUITY_L.csv`) is used so search and reports still work.
"""
import csv
import io
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from ..config import COMPANY_LIST_TTL_DAYS
from .base import SourceUnavailable  # noqa: F401  (re-exported for callers)

NSE_EQUITY_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "data" / "EQUITY_L.csv"
KEEP_SERIES = {"EQ", "BE"}
RETRY_AFTER_FAILURE_SECONDS = 600       # don't hammer a failing download on every search
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; StockAnalystV0/0.1; personal research tool)",
    "Accept": "text/csv,*/*",
}

_lock = threading.Lock()
_companies: dict[str, dict] = {}        # SYMBOL (upper-case) -> {symbol, name, series, isin}
_updated_at: datetime | None = None     # when the list was last loaded from NSE (None = never)
_next_attempt = 0.0                     # monotonic time before which we won't retry a failed download
_from_snapshot = False


def parse_equity_csv(text: str) -> list[dict]:
    """Parse NSE's CSV. Header names have stray spaces, so normalise them."""
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for raw in reader:
        row = {(k or "").strip().upper(): (v or "").strip() for k, v in raw.items()}
        series = row.get("SERIES", "")
        symbol = row.get("SYMBOL", "")
        if series not in KEEP_SERIES or not symbol:
            continue
        rows.append({
            "symbol": symbol,
            "name": row.get("NAME OF COMPANY", ""),
            "series": series,
            "isin": row.get("ISIN NUMBER", ""),
        })
    return rows


def _now() -> datetime:
    return datetime.now(timezone.utc)


def reset() -> None:
    """Forget everything (tests)."""
    global _companies, _updated_at, _next_attempt, _from_snapshot
    with _lock:
        _companies, _updated_at, _next_attempt, _from_snapshot = {}, None, 0.0, False


def last_updated() -> datetime | None:
    return _updated_at


def is_stale() -> bool:
    t = _updated_at
    return t is None or _now() - t > timedelta(days=COMPANY_LIST_TTL_DAYS)


def store_companies(rows: list[dict]) -> int:
    """Merge `rows` into the in-memory list (matching symbols are updated, as an upsert would) and mark the list as
    freshly loaded from NSE."""
    global _companies, _updated_at, _from_snapshot
    with _lock:
        merged = dict(_companies)
        for r in rows:
            merged[r["symbol"].upper()] = {"symbol": r["symbol"], "name": r["name"],
                                           "series": r.get("series", ""), "isin": r.get("isin", "")}
        _companies, _updated_at, _from_snapshot = merged, _now(), False
    return len(rows)


def _load_snapshot() -> bool:
    """Fall back to the bundled list. It is never marked as fresh, so a real download is retried later."""
    global _companies, _from_snapshot
    try:
        rows = parse_equity_csv(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except OSError:
        return False
    if not rows:
        return False
    with _lock:
        _companies = {r["symbol"].upper(): r for r in rows}
        _from_snapshot = True
    return True


def refresh_companies(force: bool = False) -> int:
    """Download the list if it is older than a week. Returns rows loaded (0 if skipped or it failed softly).

    On a failed download the list already in memory is kept; with nothing loaded the bundled snapshot is used. Only
    when there is no snapshot either does this raise SourceUnavailable.
    """
    global _next_attempt
    if not force and not is_stale():
        return 0
    if not force and time.monotonic() < _next_attempt:
        return 0
    try:
        resp = requests.get(NSE_EQUITY_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        rows = parse_equity_csv(resp.text)
        if not rows:
            raise ValueError("no usable rows in NSE list")
        _next_attempt = 0.0
        return store_companies(rows)
    except (requests.RequestException, ValueError) as exc:
        _next_attempt = time.monotonic() + RETRY_AFTER_FAILURE_SECONDS
        if _companies:
            return 0
        if _load_snapshot():
            return 0
        raise SourceUnavailable(f"Couldn't fetch the NSE company list: {exc}") from exc


def ensure_loaded() -> None:
    """Make sure some company list is in memory (names are looked up from it). Never raises."""
    if _companies:
        return
    try:
        refresh_companies()
    except SourceUnavailable:
        pass


def using_snapshot() -> bool:
    return _from_snapshot


def search(q: str, limit: int = 10) -> list[dict]:
    """Companies whose symbol or name contains q (any case). Exact symbol first, then symbol prefix,
    then name prefix, then the rest; shorter symbols first within a group."""
    q = q.strip().lower()
    if not q:
        return []
    ranked = []
    for company in list(_companies.values()):
        symbol, name = company["symbol"].lower(), company["name"].lower()
        if q not in symbol and q not in name:
            continue
        rank = 0 if symbol == q else 1 if symbol.startswith(q) else 2 if name.startswith(q) else 3
        ranked.append((rank, len(symbol), symbol, company))
    ranked.sort(key=lambda item: item[:3])
    return [{"symbol": c["symbol"], "name": c["name"]} for *_, c in ranked[:limit]]


def get_company(symbol: str) -> dict | None:
    company = _companies.get(symbol.strip().upper())
    return {"symbol": company["symbol"], "name": company["name"]} if company else None
