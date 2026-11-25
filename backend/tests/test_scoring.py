from pathlib import Path

import pytest

from backend.app import scoring
from backend.app.format import crore, indian_int, pct, rupees
from backend.app.scoring import NewsLabel, QuestionResult
from backend.app.sources.screener import Peer, ScreenerData, parse_company_page

FIX = Path(__file__).parent / "fixtures"


def make(**kw) -> ScreenerData:
    base = dict(symbol="TEST", url="https://www.screener.in/company/TEST/consolidated/",
                fetched_at="x", consolidated=True, price=100.0, pe=20.0, roce=20.0, opm=15.0,
                quarter_labels=[f"Q{i}" for i in range(8)], sales=[100.0] * 8,
                equity_capital=10.0, reserves=90.0, borrowings=10.0, balance_as_of="Sep 2026",
                industry="Cables", broad_industry="Industrial Products",
                peers=[Peer("A", "A", 20.0), Peer("B", "B", 20.0), Peer("C", "C", 20.0)])
    base.update(kw)
    return ScreenerData(**base)


def real(symbol: str) -> ScreenerData:
    html = (FIX / f"{symbol}.html").read_text(encoding="utf-8")
    return parse_company_page(html, symbol, f"https://www.screener.in/company/{symbol}/consolidated/", "x")


# ------------------------------------------------------------------ formatting
@pytest.mark.parametrize("n,expected", [
    (0, "0"), (999, "999"), (1000, "1,000"), (7028, "7,028"), (100000, "1,00,000"),
    (420000, "4,20,000"), (12345678, "1,23,45,678"), (-149081, "-1,49,081"),
])
def test_indian_int(n, expected):
    assert indian_int(n) == expected


def test_rupee_helpers():
    assert rupees(6412) == "₹6,412"
    assert rupees(11.7, 1) == "₹11.7"
    assert crore(149081) == "₹1,49,081 Cr"
    assert pct(18, signed=True) == "+18.0%" and pct(-3.04) == "-3.0%"


# ------------------------------------------------------------------ 1. growth (green >=10, amber 0-10, red <0)
def sales_with_growth(g: float) -> list[float]:
    return [100.0] * 4 + [100.0 * (1 + g / 100)] * 4


@pytest.mark.parametrize("growth,status", [
    (18, "green"), (10, "green"), (9.9, "amber"), (0, "amber"), (-0.1, "red"), (-20, "red"),
])
def test_growth_boundaries(growth, status):
    assert scoring.score_growth(make(sales=sales_with_growth(growth))).status == status


def test_growth_text_and_fact():
    r = scoring.score_growth(make(sales=sales_with_growth(18)))
    assert r.value_display == "Sales up 18.0% over the last 4 quarters vs the 4 before"
    assert r.facts[0].value_display == "+18.0%" and r.facts[0].as_of == "Q7 quarter"
    assert "down 5.0%" in scoring.score_growth(make(sales=sales_with_growth(-5))).value_display


def test_growth_rounds_before_classifying_so_display_matches_colour():
    # 9.96% displays as "10.0%", so it must be green, not amber.
    assert scoring.score_growth(make(sales=sales_with_growth(9.96))).status == "green"


@pytest.mark.parametrize("sales", [
    [], [1.0] * 7, [1, 2, None, 4, 5, 6, 7, 8], [0.0] * 4 + [5.0] * 4, [-1.0] * 4 + [5.0] * 4,
])
def test_growth_grey_when_data_missing_or_base_not_positive(sales):
    assert scoring.score_growth(make(sales=sales)).status == "grey"


# ------------------------------------------------------------------ 2. efficiency (green >=15, amber 10-15, red <10)
@pytest.mark.parametrize("roce,status", [
    (29.9, "green"), (15, "green"), (14.9, "amber"), (10, "amber"), (9.9, "red"), (-1.7, "red"),
])
def test_roce_boundaries(roce, status):
    assert scoring.score_efficiency(make(roce=roce)).status == status


def test_efficiency_shows_margin_beside_roce_and_handles_missing():
    r = scoring.score_efficiency(make(roce=32, opm=17.0))
    assert r.value_display == "Return on capital 32.0%, profit margin 17%"
    assert r.facts[0].label == "Return on capital (ROCE)" and len(r.facts) == 2
    assert "profit margin" not in scoring.score_efficiency(make(opm=None)).value_display
    assert scoring.score_efficiency(make(roce=None)).status == "grey"


# ------------------------------------------------------------------ 3. debt (green <0.5, amber 0.5-1, red >1)
@pytest.mark.parametrize("borrowings,status", [
    (0, "green"), (49, "green"), (50, "amber"), (100, "amber"), (101, "red"), (500, "red"),
])
def test_debt_boundaries_with_net_worth_100(borrowings, status):
    d = make(equity_capital=10.0, reserves=90.0, borrowings=borrowings)
    assert scoring.score_debt(d).status == status


def test_debt_negative_net_worth_is_red():
    r = scoring.score_debt(make(equity_capital=100.0, reserves=-150.0, borrowings=10.0))
    assert r.status == "red" and "negative" in r.value_display


def test_debt_grey_when_missing_and_for_lenders():
    assert scoring.score_debt(make(borrowings=None)).status == "grey"
    r = scoring.score_debt(make(broad_industry="Banks", industry="Private Sector Bank"))
    assert r.status == "grey" and "lenders" in r.value_display
    assert scoring.score_debt(make(has_deposits=True)).status == "grey"


@pytest.mark.parametrize("broad,industry,expected", [
    ("Banks", "Private Sector Bank", True),
    ("Finance", "Non Banking Financial Company (NBFC)", True),
    ("Finance", "Housing Finance Company", True),
    ("Finance", "Stockbroking & Allied", False),
    ("Finance", "Depositories, Clearing Houses and Other Intermediaries", False),
    ("IT - Software", "Computers - Software & Consulting", False),
])
def test_lender_detection(broad, industry, expected):
    assert scoring.is_lender(make(broad_industry=broad, industry=industry)) is expected


# ------------------------------------------------------------------ 4. price (green <=1x, amber <=1.5x, red above or loss)
@pytest.mark.parametrize("pe,status", [
    (15, "green"), (20, "green"), (20.1, "amber"), (30, "amber"), (30.1, "red"), (94.8, "red"),
])
def test_price_boundaries_against_peer_median_20(pe, status):
    assert scoring.score_price(make(pe=pe)).status == status


def test_price_loss_maker_is_red_but_blank_page_is_grey():
    assert scoring.score_price(make(pe=None, price=11.7)).status == "red"
    assert scoring.score_price(make(pe=None, price=None)).status == "grey"


def test_price_grey_with_too_few_peers_and_ignores_negative_peer_pe():
    assert scoring.score_price(make(peers=[Peer("A", "A", 20.0)])).status == "grey"
    peers = [Peer("A", "A", 20.0), Peer("B", "B", 20.0), Peer("C", "C", 20.0), Peer("D", "D", -5.0)]
    r = scoring.score_price(make(peers=peers))
    assert r.status == "green" and "3 similar" in r.facts[1].label


# ------------------------------------------------------------------ 5. news
def test_news_levels():
    ok = NewsLabel(True, "good", False)
    assert scoring.score_news([]).status == "green"
    assert scoring.score_news([ok]).status == "green"
    assert scoring.score_news([ok, NewsLabel(True, "bad", False)]).status == "amber"
    assert scoring.score_news([NewsLabel(True, "bad", True)]).status == "red"


def test_news_ignores_headlines_not_about_the_company_and_grey_on_failure():
    assert scoring.score_news([NewsLabel(False, "bad", True)]).status == "green"
    assert scoring.score_news(None).status == "grey"


# ------------------------------------------------------------------ overall label
def results(*statuses: str) -> list[QuestionResult]:
    return [QuestionResult(qid, s, "") for qid, s in zip(scoring.QUESTION_ORDER, statuses)]


@pytest.mark.parametrize("statuses,code", [
    (("green", "green", "green", "amber", "green"), "looks_solid"),   # 4 green, no red
    (("green", "green", "green", "grey", "grey"), "looks_solid"),     # exactly 3 green; grey doesn't count against
    (("green", "green", "amber", "amber", "amber"), "mixed"),         # only 2 green
    (("green", "green", "green", "red", "green"), "mixed"),           # one red blocks "solid"
    (("red", "red", "green", "green", "green"), "be_careful"),        # 2 reds
    (("green", "green", "green", "green", "red"), "be_careful"),      # news red alone
    (("grey",) * 5, "mixed"),
])
def test_overall_label(statuses, code):
    assert scoring.overall_label(results(*statuses))["code"] == code


def test_lenders_are_capped_at_mixed_but_can_still_be_careful():
    solid = results("green", "green", "grey", "green", "green")
    assert scoring.overall_label(solid)["code"] == "looks_solid"
    assert scoring.overall_label(solid, lender=True) == {"code": "mixed", "display": "Mixed"}
    bad = results("red", "red", "grey", "green", "green")
    assert scoring.overall_label(bad, lender=True)["code"] == "be_careful"


# ------------------------------------------------------------------ against real pages
def test_real_abb_scores():
    rs, label = scoring.score_all(real("ABB"), [])
    by = {r.id: r.status for r in rs}
    assert [r.id for r in rs] == scoring.QUESTION_ORDER
    assert by["growth"] == "green"       # sales up 11.7% over the last 4 quarters
    assert by["efficiency"] == "green"   # ROCE 29.9
    assert by["debt"] == "green"         # 145 / 9,339
    assert by["price"] == "amber"        # P/E 94.8 vs 85.8 median = 1.10x
    assert by["news"] == "green"
    assert label["code"] == "looks_solid"


def test_real_bank_is_never_solid_and_debt_is_not_applicable():
    rs, label = scoring.score_all(real("HDFCBANK"), [])
    assert {r.id: r.status for r in rs}["debt"] == "grey"
    assert label["code"] != "looks_solid"


def test_real_loss_maker_is_be_careful():
    rs, label = scoring.score_all(real("IDEA"), [])
    by = {r.id: r.status for r in rs}
    assert by["debt"] == "red" and by["price"] == "red" and label["code"] == "be_careful"


def test_real_blank_page_is_mostly_grey():
    by = {r.id: r.status for r in scoring.score_all(real("GILLETTE"), [])[0]}
    assert by["efficiency"] == "grey" and by["price"] == "grey"
