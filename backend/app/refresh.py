"""Refresh all (Phase 2 spec, section 4.5): rebuild every saved stock's report, one at a time."""
import logging
import threading

from . import flags, holdings, report
from .errors import ApiError

log = logging.getLogger("stock_analyst.refresh")
_lock = threading.Lock()

BUSY = "A refresh is already running. Try again in a minute."
KEPT = "Screener.in couldn't be reached, so the earlier report was kept."
NO_EARLIER = "Screener.in couldn't be reached."
UNEXPECTED = "Something unexpected went wrong."


def _codes(h: dict) -> set[str]:
    """Flag codes that come from stored reports alone (spec decision D5)."""
    found = report.recent_reports(h["symbol"], 2)
    return flags.report_codes(watching=h["watching"], buy_price=h["buy_price"],
                              latest=found[0] if found else None, previous=found[1] if len(found) > 1 else None)


def refresh_all() -> dict:
    if not _lock.acquire(blocking=False):
        raise ApiError("bad_request", BUSY)
    try:
        return _run()
    finally:
        _lock.release()


def _run() -> dict:
    saved = holdings.list_holdings()
    before = {h["symbol"]: _codes(h) for h in saved}      # measured before anything changes
    deps = report.Deps()
    refreshed: list[str] = []
    failed: list[dict] = []

    for h in saved:
        symbol = h["symbol"]
        try:
            report.refresh_keep_previous(symbol, deps)
            refreshed.append(symbol)
        except report.ScreenerUnavailable:
            failed.append({"symbol": symbol, "reason": KEPT if report.latest_report(symbol) else NO_EARLIER})
        except ApiError as exc:
            failed.append({"symbol": symbol, "reason": exc.message})
        except Exception:
            log.exception("Refreshing %s failed", symbol)
            failed.append({"symbol": symbol, "reason": UNEXPECTED})

    new_flags = [h["symbol"] for h in saved
                 if h["symbol"] in refreshed and _codes(h) - before[h["symbol"]]]
    return {"refreshed": refreshed, "failed": failed, "new_flags": new_flags}
