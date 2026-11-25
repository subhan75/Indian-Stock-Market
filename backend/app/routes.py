from fastapi import APIRouter, Query

from .db import connect
from .errors import ApiError
from .sources import nse

router = APIRouter(prefix="/api")


@router.get("/stocks/search")
def search_stocks(q: str = Query("", max_length=80)):
    try:
        nse.refresh_companies()
    except nse.SourceUnavailable as exc:
        raise ApiError("source_unavailable", str(exc))
    return nse.search(q)


@router.get("/reports/recent")
def recent_reports(limit: int = Query(10, ge=1, le=50)):
    """Newest report per stock, newest first."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT r.symbol, COALESCE(c.name, r.symbol) AS name, r.label, r.generated_at
            FROM reports r
            JOIN (SELECT symbol, MAX(generated_at) AS g FROM reports GROUP BY symbol) m
              ON m.symbol = r.symbol AND m.g = r.generated_at
            LEFT JOIN companies c ON c.symbol = r.symbol
            ORDER BY r.generated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
