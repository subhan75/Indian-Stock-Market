"""NSE equity list: download EQUITY_L.csv weekly, keep EQ and BE series, serve search."""
import csv
import io
from datetime import datetime, timedelta, timezone

import requests

from ..config import COMPANY_LIST_TTL_DAYS
from ..db import connect
from .base import SourceUnavailable  # noqa: F401  (re-exported for callers)

NSE_EQUITY_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
KEEP_SERIES = {"EQ", "BE"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; StockAnalystV0/0.1; personal research tool)",
    "Accept": "text/csv,*/*",
}


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


def last_updated() -> datetime | None:
    with connect() as conn:
        row = conn.execute("SELECT MAX(updated_at) AS t FROM companies").fetchone()
    return datetime.fromisoformat(row["t"]) if row and row["t"] else None


def is_stale() -> bool:
    t = last_updated()
    return t is None or _now() - t > timedelta(days=COMPANY_LIST_TTL_DAYS)


def store_companies(rows: list[dict]) -> int:
    stamp = _now().isoformat()
    with connect() as conn:
        conn.executemany(
            "INSERT INTO companies (symbol, name, series, isin, updated_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET name=excluded.name, series=excluded.series, "
            "isin=excluded.isin, updated_at=excluded.updated_at",
            [(r["symbol"], r["name"], r["series"], r["isin"], stamp) for r in rows],
        )
    return len(rows)


def refresh_companies(force: bool = False) -> int:
    """Download and store the list if it is older than a week. Returns rows stored (0 if skipped).

    On failure, keeps the existing list and raises SourceUnavailable only if there is nothing to fall back on.
    """
    if not force and not is_stale():
        return 0
    try:
        resp = requests.get(NSE_EQUITY_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        rows = parse_equity_csv(resp.text)
        if not rows:
            raise ValueError("no usable rows in NSE list")
        return store_companies(rows)
    except (requests.RequestException, ValueError) as exc:
        if last_updated() is None:
            raise SourceUnavailable(f"Couldn't fetch the NSE company list: {exc}") from exc
        return 0


def search(q: str, limit: int = 10) -> list[dict]:
    q = q.strip()
    if not q:
        return []
    like_prefix = f"{q}%"
    like_any = f"%{q}%"
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT symbol, name FROM companies
            WHERE symbol LIKE ? COLLATE NOCASE OR name LIKE ? COLLATE NOCASE
            ORDER BY
              CASE
                WHEN symbol = ? COLLATE NOCASE THEN 0
                WHEN symbol LIKE ? COLLATE NOCASE THEN 1
                WHEN name LIKE ? COLLATE NOCASE THEN 2
                ELSE 3
              END,
              length(symbol), symbol
            LIMIT ?
            """,
            (like_any, like_any, q, like_prefix, like_prefix, limit),
        ).fetchall()
    return [{"symbol": r["symbol"], "name": r["name"]} for r in rows]


def get_company(symbol: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT symbol, name FROM companies WHERE symbol = ? COLLATE NOCASE", (symbol,)
        ).fetchone()
    return dict(row) if row else None
