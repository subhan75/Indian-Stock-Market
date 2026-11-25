import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import holdings, refresh, report, store
from backend.app.errors import ApiError
from backend.app.main import app
from backend.app.sources import news as news_src
from backend.app.sources import nse, prices
from backend.app.sources.base import SourceUnavailable
from backend.app.sources.screener import parse_company_page

FIX = Path(__file__).parent / "fixtures"
COMPANIES = [{"symbol": s, "name": n, "series": "EQ", "isin": s} for s, n in
             [("ABB", "ABB India Limited"), ("TITAN", "Titan Company Limited"), ("INFY", "Infosys Limited"),
              ("IDEA", "Vodafone Idea Limited")]]


@pytest.fixture(autouse=True)
def seeded(monkeypatch):
    nse.store_companies(COMPANIES)
    monkeypatch.setattr(nse, "refresh_companies", lambda force=False: 0)
    monkeypatch.setattr(report, "get_report", lambda *a, **k: None)
    monkeypatch.setattr(report, "Deps", lambda: object())          # no AI client is built in these tests


def add(symbol, shares=10, price=100.0, watching=False):
    body = {"symbol": symbol, "watching": watching}
    if not watching:
        body.update(shares=shares, buy_price=price)
    holdings.create(body)


def make_report(symbol, label="mixed", when=None, price=100.0, news=None):
    when = when or (datetime.now(prices.IST) - timedelta(days=1)).isoformat(timespec="seconds")
    display = {"looks_solid": "Looks solid", "mixed": "Mixed", "be_careful": "Be careful"}[label]
    return {"symbol": symbol, "generated_at": when, "label": {"code": label, "display": display},
            "price": {"value": price}, "news": news or [], "sources": [{"name": "Google News", "ok": True}],
            "questions": [{"id": i, "status": "green"} for i in ("growth", "efficiency", "debt", "price", "news")]}


def scripted(monkeypatch, outcomes):
    """Replace the per-stock refresh. outcomes: symbol -> report dict to save, or an exception to raise."""
    calls = []

    def fake(symbol, deps=None):
        calls.append(symbol)
        outcome = outcomes[symbol]
        if isinstance(outcome, Exception):
            raise outcome
        outcome["generated_at"] = datetime.now(prices.IST).isoformat(timespec="seconds")
        report._save(outcome)
        return outcome

    monkeypatch.setattr(report, "refresh_keep_previous", fake)
    return calls


# ------------------------------------------------------------------ orchestration
def test_no_stocks_is_an_empty_success():
    assert refresh.refresh_all() == {"refreshed": [], "failed": [], "new_flags": []}


def test_refreshes_every_stock_in_the_order_they_were_added_including_watching(monkeypatch):
    add("INFY"), add("TITAN", watching=True), add("ABB")
    calls = scripted(monkeypatch, {s: make_report(s) for s in ("INFY", "TITAN", "ABB")})
    result = refresh.refresh_all()
    assert calls == ["INFY", "TITAN", "ABB"] and result["refreshed"] == ["INFY", "TITAN", "ABB"]
    assert result["failed"] == [] and result["new_flags"] == []


def test_one_failure_never_stops_the_others_and_each_reason_is_plain(monkeypatch):
    add("ABB"), add("TITAN"), add("INFY"), add("IDEA")
    report._save(make_report("ABB"))          # ABB has an earlier report, TITAN does not
    calls = scripted(monkeypatch, {
        "ABB": report.ScreenerUnavailable("ABB"), "TITAN": report.ScreenerUnavailable("TITAN"),
        "INFY": ApiError("not_found", "INFY isn't on the NSE equity list. Check the symbol or search by company name."),
        "IDEA": make_report("IDEA"),
    })
    result = refresh.refresh_all()
    assert calls == ["ABB", "TITAN", "INFY", "IDEA"]
    assert result["refreshed"] == ["IDEA"]
    assert result["failed"] == [
        {"symbol": "ABB", "reason": "Screener.in couldn't be reached, so the earlier report was kept."},
        {"symbol": "TITAN", "reason": "Screener.in couldn't be reached."},
        {"symbol": "INFY", "reason": "INFY isn't on the NSE equity list. Check the symbol or search by company name."},
    ]


def test_an_unexpected_error_is_reported_without_leaking_details(monkeypatch):
    add("ABB"), add("TITAN")
    scripted(monkeypatch, {"ABB": RuntimeError("secret internal detail"), "TITAN": make_report("TITAN")})
    result = refresh.refresh_all()
    assert result["failed"] == [{"symbol": "ABB", "reason": "Something unexpected went wrong."}]
    assert result["refreshed"] == ["TITAN"]


# ------------------------------------------------------------------ new_flags
def test_new_flags_lists_stocks_that_gained_a_flag_code(monkeypatch):
    add("ABB"), add("TITAN"), add("INFY")
    for s in ("ABB", "TITAN", "INFY"):
        report._save(make_report(s, "looks_solid", when="2026-11-20T10:00:00+05:30"))
    scripted(monkeypatch, {"ABB": make_report("ABB", "looks_solid"),           # unchanged
                           "TITAN": make_report("TITAN", "be_careful"),        # gains be_careful and label_worse
                           "INFY": make_report("INFY", "looks_solid", price=70.0)})    # gains price_drop (bought at 100)
    assert refresh.refresh_all()["new_flags"] == ["TITAN", "INFY"]


def test_an_existing_flag_is_not_new_again(monkeypatch):
    add("ABB")
    report._save(make_report("ABB", "be_careful", when="2026-11-20T10:00:00+05:30"))
    scripted(monkeypatch, {"ABB": make_report("ABB", "be_careful")})
    assert refresh.refresh_all()["new_flags"] == []


def test_a_second_flag_reason_on_an_already_flagged_stock_counts_as_new(monkeypatch):
    add("ABB")
    report._save(make_report("ABB", "be_careful", when="2026-11-20T10:00:00+05:30"))
    scripted(monkeypatch, {"ABB": make_report("ABB", "be_careful", price=50.0)})      # adds price_drop
    assert refresh.refresh_all()["new_flags"] == ["ABB"]


def test_a_failed_refresh_cannot_create_a_new_flag(monkeypatch):
    add("ABB")
    report._save(make_report("ABB", "looks_solid", when="2026-11-20T10:00:00+05:30"))
    scripted(monkeypatch, {"ABB": report.ScreenerUnavailable("ABB")})
    assert refresh.refresh_all()["new_flags"] == []


def test_first_ever_report_with_a_bad_label_is_a_new_flag(monkeypatch):
    add("ABB")
    scripted(monkeypatch, {"ABB": make_report("ABB", "be_careful")})
    assert refresh.refresh_all()["new_flags"] == ["ABB"]


def test_watching_stocks_can_gain_flags_but_never_price_drops(monkeypatch):
    add("TITAN", watching=True)
    scripted(monkeypatch, {"TITAN": make_report("TITAN", "be_careful", price=1.0)})
    assert refresh.refresh_all()["new_flags"] == ["TITAN"]


def test_flag_state_is_measured_before_any_refresh_starts(monkeypatch):
    add("ABB"), add("TITAN")
    for s in ("ABB", "TITAN"):
        report._save(make_report(s, "looks_solid", when="2026-11-20T10:00:00+05:30"))
    seen = {}

    def fake(symbol, deps=None):
        seen[symbol] = len(report.recent_reports(symbol, 5))        # reports stored when this stock is reached
        rep = make_report(symbol, "be_careful")
        rep["generated_at"] = datetime.now(prices.IST).isoformat(timespec="seconds")
        report._save(rep)
        return rep

    monkeypatch.setattr(report, "refresh_keep_previous", fake)
    assert refresh.refresh_all()["new_flags"] == ["ABB", "TITAN"]
    assert seen == {"ABB": 1, "TITAN": 1}                           # TITAN untouched until its own turn


# ------------------------------------------------------------------ one refresh at a time
def test_a_second_refresh_is_rejected_while_one_is_running_and_the_lock_is_released(monkeypatch):
    add("ABB")
    started, release = threading.Event(), threading.Event()

    def slow(symbol, deps=None):
        started.set()
        release.wait(5)
        return make_report(symbol)

    monkeypatch.setattr(report, "refresh_keep_previous", slow)
    first = {}
    t = threading.Thread(target=lambda: first.update(refresh.refresh_all()))
    t.start()
    assert started.wait(5)
    with pytest.raises(ApiError) as err:
        refresh.refresh_all()
    assert err.value.code == "bad_request" and err.value.message == "A refresh is already running. Try again in a minute."
    release.set()
    t.join(5)
    assert first["refreshed"] == ["ABB"]
    monkeypatch.setattr(report, "refresh_keep_previous", lambda s, d=None: make_report(s))
    assert refresh.refresh_all()["refreshed"] == ["ABB"]              # lock was released


def test_the_lock_is_released_even_if_the_run_blows_up(monkeypatch):
    monkeypatch.setattr(holdings, "list_holdings", lambda: (_ for _ in ()).throw(RuntimeError("db gone")))
    with pytest.raises(RuntimeError):
        refresh.refresh_all()
    monkeypatch.undo()
    mine = refresh._lock_for(store.current().user_id)
    assert mine.acquire(blocking=False)
    mine.release()


# ------------------------------------------------------------------ the real per-stock refresh (decision D3)
def page(symbol="ABB"):
    html = (FIX / f"{symbol}.html").read_text(encoding="utf-8")
    return parse_company_page(html, symbol, f"https://www.screener.in/company/{symbol}/consolidated/",
                              datetime.now(timezone.utc).isoformat())


def real_deps(screener_ok=True, news_ok=True):
    def screener(symbol):
        if not screener_ok:
            raise SourceUnavailable("down")
        return page("ABB")

    now = datetime.now(timezone.utc)
    return report.Deps.__wrapped__(screener=screener) if False else _Deps(
        screener=screener,
        price=lambda s, fb, url: prices.fetch_price(s, fb, url, yf_fetch=lambda _: (7028.5, 6868.5)),
        news=lambda name: news_src.NewsResult(news_ok, [], now, "https://n.test"),
        llm=None)


class _Deps:
    def __init__(self, screener, price, news, llm):
        self.screener, self.price, self.news, self.llm = screener, price, news, llm


def test_real_refresh_saves_when_screener_works():
    rep = report.refresh_keep_previous("abb", real_deps())
    assert rep["symbol"] == "ABB" and report.latest_report("ABB")["generated_at"] == rep["generated_at"]
    assert rep["price"]["value"] == 7028.5 and all("serious" in n for n in rep["news"])


def test_real_refresh_keeps_the_previous_report_when_screener_is_down():
    good = report.refresh_keep_previous("ABB", real_deps())
    with pytest.raises(report.ScreenerUnavailable):
        report.refresh_keep_previous("ABB", real_deps(screener_ok=False))
    assert report.latest_report("ABB")["generated_at"] == good["generated_at"]
    assert len(report.recent_reports("ABB", 5)) == 1


def test_real_refresh_still_saves_when_only_news_is_down():
    rep = report.refresh_keep_previous("ABB", real_deps(news_ok=False))
    assert {q["id"]: q["status"] for q in rep["questions"]}["news"] == "grey"
    assert report.latest_report("ABB") is not None


# ------------------------------------------------------------------ the endpoint
def test_endpoint_returns_the_documented_shape_and_busy_error(monkeypatch):
    add("ABB")
    scripted(monkeypatch, {"ABB": make_report("ABB", "be_careful")})
    with TestClient(app) as client:
        r = client.post("/api/refresh-all")
        assert r.status_code == 200
        assert r.json() == {"refreshed": ["ABB"], "failed": [], "new_flags": ["ABB"]}
        mine = refresh._lock_for(store.current().user_id)
        assert mine.acquire(blocking=False)
        try:
            busy = client.post("/api/refresh-all")
        finally:
            mine.release()
        assert busy.status_code == 400
        assert busy.json() == {"error": {"code": "bad_request",
                                         "message": "A refresh is already running. Try again in a minute."}}


# ------------------------------------------------------------------ one user's refresh never blocks another's
def test_each_person_has_their_own_refresh_lock():
    assert refresh._lock_for("user-a") is refresh._lock_for("user-a")
    assert refresh._lock_for("user-a") is not refresh._lock_for("user-b")


def test_someone_elses_running_refresh_does_not_block_mine(monkeypatch):
    add("ABB")
    scripted(monkeypatch, {"ABB": make_report("ABB")})
    other = refresh._lock_for("another-user")
    assert other.acquire(blocking=False)
    try:
        assert refresh.refresh_all()["refreshed"] == ["ABB"]
    finally:
        other.release()


# ------------------------------------------------------------------ refreshing one stock (what the page calls per stock)
def test_refresh_one_success_shape(monkeypatch):
    add("ABB")
    report._save(make_report("ABB", "looks_solid", when="2026-11-20T10:00:00+05:30"))
    scripted(monkeypatch, {"ABB": make_report("ABB", "looks_solid")})
    assert refresh.refresh_one("abb") == {"symbol": "ABB", "refreshed": True, "failed": None, "new_flag": False}


def test_refresh_one_reports_a_screener_failure_and_keeps_the_old_report(monkeypatch):
    add("ABB")
    report._save(make_report("ABB"))
    scripted(monkeypatch, {"ABB": report.ScreenerUnavailable("ABB")})
    assert refresh.refresh_one("ABB") == {
        "symbol": "ABB", "refreshed": False, "new_flag": False,
        "failed": {"reason": "Screener.in couldn't be reached, so the earlier report was kept."}}


def test_refresh_one_with_no_earlier_report_says_so(monkeypatch):
    add("ABB")
    scripted(monkeypatch, {"ABB": report.ScreenerUnavailable("ABB")})
    assert refresh.refresh_one("ABB")["failed"] == {"reason": "Screener.in couldn't be reached."}


def test_refresh_one_flags_only_a_newly_gained_reason(monkeypatch):
    add("ABB")
    report._save(make_report("ABB", "looks_solid", when="2026-11-20T10:00:00+05:30"))
    scripted(monkeypatch, {"ABB": make_report("ABB", "be_careful")})
    assert refresh.refresh_one("ABB")["new_flag"] is True
    scripted(monkeypatch, {"ABB": make_report("ABB", "be_careful")})
    assert refresh.refresh_one("ABB")["new_flag"] is False, "the same flag is not new the second time"


def test_refresh_one_works_for_a_watched_stock(monkeypatch):
    add("TITAN", watching=True)
    scripted(monkeypatch, {"TITAN": make_report("TITAN")})
    assert refresh.refresh_one("TITAN")["refreshed"] is True


def test_refresh_one_for_a_stock_you_do_not_have_is_404(monkeypatch):
    scripted(monkeypatch, {})
    with pytest.raises(ApiError) as err:
        refresh.refresh_one("ABB")
    assert err.value.code == "not_found" and err.value.message == "ABB isn't in your stocks."
    with pytest.raises(ApiError) as bad:
        refresh.refresh_one("not a symbol!")
    assert bad.value.code == "bad_request"


def test_refresh_one_hides_unexpected_errors(monkeypatch):
    add("ABB")
    scripted(monkeypatch, {"ABB": RuntimeError("secret internal detail")})
    out = refresh.refresh_one("ABB")
    assert out["failed"] == {"reason": "Something unexpected went wrong."} and "secret" not in str(out)


def test_a_database_failure_while_refreshing_is_not_hidden_as_a_stock_failure(monkeypatch):
    add("ABB")
    scripted(monkeypatch, {"ABB": store.StoreError("db down")})
    with pytest.raises(store.StoreError):
        refresh.refresh_one("ABB")


def test_refresh_one_endpoint(monkeypatch):
    add("ABB")
    scripted(monkeypatch, {"ABB": make_report("ABB", "be_careful")})
    with TestClient(app) as client:
        r = client.post("/api/holdings/ABB/refresh")
        assert r.status_code == 200
        assert r.json() == {"symbol": "ABB", "refreshed": True, "failed": None, "new_flag": True}
        missing = client.post("/api/holdings/TITAN/refresh")
        assert missing.status_code == 404
        assert missing.json() == {"error": {"code": "not_found", "message": "TITAN isn't in your stocks."}}
