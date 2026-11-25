import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app import holdings, portfolio, report
from backend.app.format import percent_direction, rupees_auto, signed_rupees
from backend.app.main import app
from backend.app.sources import nse, screener
from backend.app.sources.prices import IST

COMPANIES = [
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance Limited", "series": "EQ", "isin": "1"},
    {"symbol": "ABB", "name": "ABB India Limited", "series": "EQ", "isin": "2"},
    {"symbol": "IDEA", "name": "Vodafone Idea Limited", "series": "EQ", "isin": "3"},
    {"symbol": "TITAN", "name": "Titan Company Limited", "series": "EQ", "isin": "4"},
    {"symbol": "INFY", "name": "Infosys Limited", "series": "EQ", "isin": "5"},
    {"symbol": "ITC", "name": "ITC Limited", "series": "EQ", "isin": "6"},
]


@pytest.fixture(autouse=True)
def seeded(monkeypatch):
    nse.store_companies(COMPANIES)
    monkeypatch.setattr(nse, "refresh_companies", lambda force=False: 0)
    monkeypatch.setattr(report, "get_report", lambda *a, **k: None)   # saving a holding builds no real report


def add(symbol, shares=None, price=None, watching=False):
    body = {"symbol": symbol, "watching": watching}
    if not watching:
        body.update(shares=shares, buy_price=price)
    return holdings.create(body)


def store(symbol, label="mixed", when="2026-11-25T10:00:00+05:30", price=None, greys=(), news=None, news_ok=True):
    display = {"looks_solid": "Looks solid", "mixed": "Mixed", "be_careful": "Be careful"}[label]
    rep = {"symbol": symbol, "generated_at": when, "label": {"code": label, "display": display},
           "price": {"value": price}, "news": news or [], "sources": [{"name": "Google News", "ok": news_ok}],
           "questions": [{"id": i, "status": "grey" if i in greys else "green"}
                         for i in ("growth", "efficiency", "debt", "price", "news")]}
    report._save(rep)
    return rep


def view(prices=None, now=None):
    prices = prices or {}
    return portfolio.build(price_fn=lambda s: prices.get(s), now=now)


def row(v, symbol):
    return next(r for r in v["rows"] if r["symbol"] == symbol)


# ------------------------------------------------------------------ formatting helpers
@pytest.mark.parametrize("gain,pct,expected", [
    (66300, 15.8, "+₹66,300 (+15.8%)"), (-5000, -3.2, "-₹5,000 (-3.2%)"), (0, 0, "₹0 (0.0%)"),
    (0.3, 0.001, "₹0 (0.0%)"), (3, 0.01, "+₹3 (0.0%)"), (-3, -0.01, "-₹3 (0.0%)"),
    (1234567, 12.34, "+₹12,34,567 (+12.3%)"), (-0.4, -0.2, "-₹0 (-0.2%)"),
])
def test_signed_rupees(gain, pct, expected):
    assert signed_rupees(gain, pct) == expected


def test_direction_and_auto_price():
    assert [percent_direction(x) for x in (15.8, -3.2, 0.04, -0.04, 0)] == ["up", "down", "flat", "flat", "flat"]
    assert rupees_auto(7028) == "₹7,028" and rupees_auto(7028.5) == "₹7,028.50" and rupees_auto(11.7) == "₹11.70"


# ------------------------------------------------------------------ one row, hand-computed
def test_gain_row_matches_hand_calculation():
    add("BAJFINANCE", 50, 720.0)
    store("BAJFINANCE", "looks_solid")
    v = view({"BAJFINANCE": 920.0})
    r = row(v, "BAJFINANCE")
    assert r["shares"] == 50 and r["buy_price_display"] == "₹720" and r["price_display"] == "₹920"
    assert r["value_display"] == "₹46,000"                      # 50 x 920
    assert r["gain_display"] == "+₹10,000 (+27.8%)"             # 46,000 - 36,000, on 36,000
    assert r["direction"] == "up" and r["price_source"] == "live"
    assert r["label"] == {"code": "looks_solid", "display": "Looks solid"} and r["has_report"] is True
    assert r["report_url"] == "/report.html?symbol=BAJFINANCE" and r["report_updated_display"] == "25 Nov"
    assert v["totals"] == {"invested_display": "₹36,000", "value_display": "₹46,000",
                           "gain_display": "+₹10,000 (+27.8%)", "direction": "up", "excluded": 0, "note": None}


def test_loss_and_flat_rows():
    add("ABB", 10, 7000.5)
    add("TITAN", 4, 3000)
    store("ABB"), store("TITAN")
    v = view({"ABB": 6000.0, "TITAN": 3000.0})
    assert row(v, "ABB")["gain_display"] == "-₹10,005 (-14.3%)" and row(v, "ABB")["direction"] == "down"
    assert row(v, "TITAN")["gain_display"] == "₹0 (0.0%)" and row(v, "TITAN")["direction"] == "flat"


def test_buy_price_with_paise_is_shown_with_two_decimals():
    add("ABB", 1, 720.5)
    assert row(view({"ABB": 720.5}), "ABB")["buy_price_display"] == "₹720.50"


# ------------------------------------------------------------------ totals across several rows
def test_totals_add_up_across_rows_with_indian_grouping():
    add("ABB", 100, 5000)          # invested 5,00,000   value 6,00,000
    add("BAJFINANCE", 50, 720)     # invested 36,000     value 46,000
    add("IDEA", 1000, 15)          # invested 15,000     value 11,700
    v = view({"ABB": 6000.0, "BAJFINANCE": 920.0, "IDEA": 11.7})
    t = v["totals"]
    assert t["invested_display"] == "₹5,51,000" and t["value_display"] == "₹6,57,700"
    assert t["gain_display"] == "+₹1,06,700 (+19.4%)" and t["direction"] == "up" and t["excluded"] == 0


# ------------------------------------------------------------------ price fallbacks and exclusions
def test_price_falls_back_to_the_report_then_to_unavailable():
    add("ABB", 10, 100.0)
    add("TITAN", 10, 100.0)
    store("ABB", price=120.0)       # report knows a price
    store("TITAN", price=None)      # report has none
    v = view({})                    # live prices all failed
    assert row(v, "ABB")["price_source"] == "report" and row(v, "ABB")["value_display"] == "₹1,200"
    t = row(v, "TITAN")
    assert t["price_source"] is None and t["price_display"] == "Price unavailable"
    assert t["value_display"] is None and t["gain_display"] is None and t["direction"] is None
    assert v["totals"]["invested_display"] == "₹1,000" and v["totals"]["excluded"] == 1
    assert v["totals"]["note"] == "1 stock isn't included because its price couldn't be fetched."


def test_a_throwing_price_function_is_treated_as_no_live_price():
    add("ABB", 10, 100.0)
    store("ABB", price=110.0)

    def boom(_):
        raise RuntimeError("yahoo exploded")

    r = portfolio.build(price_fn=boom)["rows"][0]
    assert r["price_source"] == "report" and r["price_display"] == "₹110"


def test_all_prices_missing_gives_zero_totals_and_a_plural_note():
    add("ABB", 10, 100.0)
    add("TITAN", 10, 100.0)
    t = view({})["totals"]
    assert (t["invested_display"], t["value_display"], t["gain_display"], t["direction"]) == \
           ("₹0", "₹0", "₹0 (0.0%)", "flat")
    assert t["excluded"] == 2 and t["note"] == "2 stocks aren't included because their prices couldn't be fetched."


def test_empty_portfolio():
    v = view()
    assert v["rows"] == [] and v["totals"]["gain_display"] == "₹0 (0.0%)" and v["totals"]["note"] is None


# ------------------------------------------------------------------ watching and missing reports
def test_watching_rows_show_a_price_but_no_money_columns_and_stay_out_of_totals():
    add("TITAN", watching=True)
    store("TITAN", "looks_solid", price=3500.0)
    v = view({"TITAN": 3600.0})
    r = row(v, "TITAN")
    assert r["watching"] is True and r["price_display"] == "₹3,600"
    assert r["shares"] is None and r["buy_price"] is None and r["buy_price_display"] is None
    assert r["value_display"] is None and r["gain_display"] is None and r["direction"] is None
    assert v["totals"]["invested_display"] == "₹0" and v["totals"]["excluded"] == 0


def test_row_without_a_report_has_no_label_and_no_flag_even_when_far_below_cost():
    add("ABB", 10, 1000.0)
    r = row(view({"ABB": 100.0}), "ABB")
    assert r["has_report"] is False and r["label"] is None and r["report_updated_display"] is None
    assert r["flag"] == {"on": False, "reasons": [], "reason": ""}
    assert r["value_display"] == "₹1,000"                     # money columns still work without a report


# ------------------------------------------------------------------ flags inside the view
def test_price_drop_uses_the_live_price():
    add("ABB", 10, 1000.0)
    store("ABB", "looks_solid", price=990.0)                   # the report price is fine...
    r = row(view({"ABB": 750.0}), "ABB")                       # ...but the live price is 25% down
    assert r["flag"]["on"] is True and r["flag"]["reasons"][0]["code"] == "price_drop"
    assert r["flag"]["reason"] == "Price is 25% below what you paid"


def test_label_worse_uses_the_latest_two_reports():
    add("ABB", 10, 100.0)
    store("ABB", "looks_solid", when="2026-11-24T10:00:00+05:30")
    store("ABB", "mixed", when="2026-11-25T10:00:00+05:30")
    r = row(view({"ABB": 100.0}), "ABB")
    assert r["flag"]["reason"] == "Label went from Looks solid to Mixed"
    assert r["label"]["code"] == "mixed" and r["report_updated_display"] == "25 Nov"


def test_a_single_report_never_gives_label_or_news_flags():
    add("ABB", 10, 100.0)
    store("ABB", "mixed", news=[{"url": "u", "serious": True}])
    assert row(view({"ABB": 100.0}), "ABB")["flag"]["on"] is False


# ------------------------------------------------------------------ ordering (decision D1)
def test_order_flagged_first_then_value_then_watching_a_to_z():
    add("ABB", 10, 100.0)          # value 1,000
    add("INFY", 100, 10.0)         # value 5,000
    add("BAJFINANCE", 1, 100.0)    # value 200, flagged below
    add("TITAN", watching=True)
    add("IDEA", watching=True)
    store("BAJFINANCE", "be_careful")
    for s in ("ABB", "INFY"):
        store(s, "looks_solid")
    v = view({"ABB": 100.0, "INFY": 50.0, "BAJFINANCE": 200.0, "TITAN": 1.0, "IDEA": 1.0})
    # flagged first, then by value (5,000 then 1,000), then watching by company name (Titan before Vodafone Idea)
    assert [r["symbol"] for r in v["rows"]] == ["BAJFINANCE", "INFY", "ABB", "TITAN", "IDEA"]


def test_watching_rows_sort_by_company_name_not_symbol():
    add("TITAN", watching=True)    # "Titan Company Limited"
    add("IDEA", watching=True)     # "Vodafone Idea Limited"
    add("ITC", watching=True)      # "ITC Limited"
    assert [r["symbol"] for r in view()["rows"]] == ["ITC", "TITAN", "IDEA"]


def test_holdings_without_a_price_sort_after_priced_ones():
    add("ABB", 10, 100.0)
    add("INFY", 10, 100.0)
    v = view({"INFY": 100.0})
    assert [r["symbol"] for r in v["rows"]] == ["INFY", "ABB"]


# ------------------------------------------------------------------ the HTTP endpoint
def test_endpoint_returns_the_view_and_never_touches_screener(monkeypatch):
    add("ABB", 10, 100.0)
    store("ABB", "looks_solid", price=120.0)

    def forbidden(*a, **k):
        raise AssertionError("GET /api/holdings must not fetch reports or Screener pages")

    monkeypatch.setattr(screener, "fetch_company", forbidden)
    monkeypatch.setattr(report, "build_report", forbidden)
    monkeypatch.setattr(portfolio, "live_price", lambda s: 130.0)
    with TestClient(app) as client:
        r = client.get("/api/holdings")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"as_of", "totals", "rows"}
    assert set(body["rows"][0]) == {
        "symbol", "name", "watching", "shares", "buy_price", "buy_price_display", "price_display",
        "price_source", "value_display", "gain_display", "direction", "has_report", "label", "flag",
        "report_updated_display", "report_url"}
    assert body["rows"][0]["value_display"] == "₹1,300"


def test_as_of_is_formatted_in_indian_time():
    now = datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)
    assert view(now=now)["as_of"] == "25 Nov, 3:30 pm"


def test_many_holdings_fetch_prices_concurrently(monkeypatch):
    import threading
    import time

    for s in ("ABB", "INFY", "TITAN", "IDEA", "ITC", "BAJFINANCE"):
        add(s, 1, 100.0)
    seen = set()

    def slow(symbol):
        seen.add(threading.get_ident())
        time.sleep(0.3)
        return 100.0

    start = time.time()
    portfolio.build(price_fn=slow)
    assert time.time() - start < 1.2          # 6 x 0.3s run one after another would take 1.8s
    assert len(seen) > 1
