from typing import Any

from fastapi import APIRouter, Body, Query

from . import holdings, marketday, portfolio, refresh, report, store
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
    """Newest report per stock, newest first (the signed-in user's own)."""
    nse.ensure_loaded()
    rows = store.current().reports_latest_by_symbol(limit)
    out = []
    for r in rows:
        company = nse.get_company(r["symbol"])
        out.append({"symbol": r["symbol"], "name": company["name"] if company else r["symbol"],
                    "label": r["label"], "generated_at": r["generated_at"]})
    return out


@router.get("/holdings")
def list_holdings():
    return portfolio.build()


@router.post("/holdings", status_code=201)
def add_holding(body: Any = Body(...)):
    saved = holdings.create(body)
    holdings.ensure_report(saved["symbol"])
    return saved


@router.put("/holdings/{symbol}")
def edit_holding(symbol: str, body: Any = Body(...)):
    saved = holdings.update(symbol, body)
    holdings.ensure_report(saved["symbol"])
    return saved


@router.delete("/holdings/{symbol}")
def remove_holding(symbol: str):
    return holdings.delete(symbol)


@router.get("/market/today")
def market_today(refresh: bool = False):
    return marketday.get_market(refresh=refresh)


@router.post("/refresh-all")
def refresh_all():
    return refresh.refresh_all()


# Registered after /reports/recent so the literal path wins over {symbol}.
@router.get("/reports/{symbol}")
def get_report(symbol: str, refresh: bool = False):
    return report.get_report(symbol, refresh=refresh)
