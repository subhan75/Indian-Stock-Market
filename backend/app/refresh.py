"""Refreshing reports (Phase 2 spec, section 4.5).

- `refresh_all()`: rebuild every saved stock's report, one at a time, in a single request (kept for scripts).
- `refresh_one(symbol)`: the same for one stock. The web page calls this once per stock, so no single request runs
  longer than Vercel's proxy allows (120 s) and the page can show real progress ("3 of 10").

Both keep a stock's earlier report if Screener.in can't be reached, and tell you if a stock GAINED a flag reason.
"""
import logging
import threading

from . import flags, holdings, report, store
from .errors import ApiError

log = logging.getLogger("stock_analyst.refresh")

BUSY = "A refresh is already running. Try again in a minute."
KEPT = "Screener.in couldn't be reached, so the earlier report was kept."
NO_EARLIER = "Screener.in couldn't be reached."
UNEXPECTED = "Something unexpected went wrong."

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(user_id: str) -> threading.Lock:
    """One lock per person, so one user's Refresh all never blocks another's."""
    with _locks_guard:
        return _locks.setdefault(user_id, threading.Lock())


def _codes(h: dict) -> set[str]:
    """Flag codes that come from stored reports alone (spec decision D5)."""
    found = report.recent_reports(h["symbol"], 2)
    return flags.report_codes(watching=h["watching"], buy_price=h["buy_price"],
                              latest=found[0] if found else None, previous=found[1] if len(found) > 1 else None)


def _refresh_holding(h: dict, deps, before: set[str]) -> dict:
    """Refresh one stock. Returns {"refreshed": bool, "reason": str | None, "new_flag": bool}. Never raises."""
    symbol = h["symbol"]
    try:
        report.refresh_keep_previous(symbol, deps)
    except report.ScreenerUnavailable:
        return {"refreshed": False, "reason": KEPT if report.latest_report(symbol) else NO_EARLIER, "new_flag": False}
    except ApiError as exc:
        return {"refreshed": False, "reason": exc.message, "new_flag": False}
    except store.StoreError:
        raise                                            # a database problem is the whole request's problem
    except Exception:
        log.exception("Refreshing %s failed", symbol)
        return {"refreshed": False, "reason": UNEXPECTED, "new_flag": False}
    return {"refreshed": True, "reason": None, "new_flag": bool(_codes(h) - before)}


def refresh_one(symbol: str) -> dict:
    """POST /api/holdings/{symbol}/refresh"""
    symbol = holdings.clean_symbol(symbol)
    holding = holdings.get_holding(symbol)
    if holding is None:
        raise ApiError("not_found", f"{symbol} isn't in your stocks.")
    outcome = _refresh_holding(holding, report.Deps(), _codes(holding))
    return {"symbol": symbol, "refreshed": outcome["refreshed"],
            "failed": None if outcome["refreshed"] else {"reason": outcome["reason"]},
            "new_flag": outcome["new_flag"]}


def refresh_all() -> dict:
    lock = _lock_for(store.current().user_id)
    if not lock.acquire(blocking=False):
        raise ApiError("bad_request", BUSY)
    try:
        return _run()
    finally:
        lock.release()


def _run() -> dict:
    saved = holdings.list_holdings()
    before = {h["symbol"]: _codes(h) for h in saved}      # measured before anything changes
    deps = report.Deps()
    refreshed: list[str] = []
    failed: list[dict] = []
    new_flags: list[str] = []
    for h in saved:
        outcome = _refresh_holding(h, deps, before[h["symbol"]])
        if outcome["refreshed"]:
            refreshed.append(h["symbol"])
            if outcome["new_flag"]:
                new_flags.append(h["symbol"])
        else:
            failed.append({"symbol": h["symbol"], "reason": outcome["reason"]})
    return {"refreshed": refreshed, "failed": failed, "new_flags": new_flags}
