import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import ai, config, report
from backend.app.db import connect
from backend.app.main import app
from backend.app.sources import news as news_src
from backend.app.sources import nse, prices
from backend.app.sources.base import NotFound, SourceUnavailable
from backend.app.sources.screener import parse_company_page

FIX = Path(__file__).parent / "fixtures"
RealDeps = report.Deps  # tests monkeypatch report.Deps, so keep the real class
NOW = datetime.now(timezone.utc)


def page(symbol: str):
    html = (FIX / f"{symbol}.html").read_text(encoding="utf-8")
    return parse_company_page(html, symbol, f"https://www.screener.in/company/{symbol}/consolidated/",
                              NOW.isoformat())


def headline(title, days_ago, outlet="Mint", url=None):
    return news_src.Headline(title, outlet, NOW - timedelta(days=days_ago), url or f"https://n.test/{abs(hash(title))}")


class ScriptedLLM:
    """Answers the labeller and the writer by looking at which system prompt it was given."""

    def __init__(self, labels=None, writer=None):
        self.labels, self.writer, self.calls = labels, writer, []

    def complete_json(self, model, system, user):
        self.calls.append(model)
        if "label news headlines" in system:
            if isinstance(self.labels, Exception):
                raise self.labels
            return json.dumps(self.labels(json.loads(user)) if callable(self.labels) else self.labels)
        return json.dumps(self.writer(json.loads(user)) if callable(self.writer) else self.writer)


def all_neutral(payload):
    return {"labels": [{"id": h["id"], "about_company": "yes", "tone": "neutral", "serious": "no",
                        "summary": f"Summary of {h['title']}."} for h in payload["headlines"]]}


def good_writer(payload):
    ids = {f["label"]: f["id"] for f in payload["facts"]}
    growth, about = ids["Sales, last 4 quarters vs the 4 before"], ids["What the company does (company description)"]
    return {"overall": {"text": f"Sales grew about 12% over the last year [{growth}].", "cites": [growth]},
            "about": {"text": f"ABB India makes power and automation equipment [{about}].", "cites": [about]}}


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(config, "LABELLER_MODEL", "small")
    monkeypatch.setattr(config, "WRITER_MODEL", "big")
    nse.store_companies([{"symbol": "ABB", "name": "ABB India Limited", "series": "EQ", "isin": "x"},
                         {"symbol": "IDEA", "name": "Vodafone Idea Limited", "series": "EQ", "isin": "y"}])


def make_deps(symbol="ABB", headlines=None, llm="default", screener=None, news=None, price=None):
    headlines = [headline("ABB India logs record orders", 2)] if headlines is None else headlines
    return RealDeps(
        screener=screener or (lambda s: page(symbol)),
        price=price or (lambda s, fb, url: prices.fetch_price(s, fb, url, yf_fetch=lambda _: (7028.5, 6868.5))),
        news=news or (lambda name: news_src.NewsResult(True, headlines, NOW, "https://news.test")),
        llm=ScriptedLLM(all_neutral, good_writer) if llm == "default" else llm,
    )


def by_id(rep):
    return {q["id"]: q for q in rep["questions"]}


# ------------------------------------------------------------------ the full contract
def test_full_report_matches_the_contract():
    rep = report.build_report("ABB", make_deps())
    assert set(rep) == {"symbol", "name", "generated_at", "price", "label", "overall", "about", "questions",
                        "news", "facts", "sources", "ai_text", "disclaimer"}
    assert rep["symbol"] == "ABB" and rep["name"] == "ABB India Limited"
    assert rep["disclaimer"] == "Research aid, not financial advice."
    assert rep["generated_at"].endswith("+05:30")
    assert rep["price"] == {"display": "₹7,028.50", "change_display": "+2.3%", "direction": "up",
                            "as_of": rep["price"]["as_of"], "value": 7028.5}
    assert [q["id"] for q in rep["questions"]] == ["growth", "efficiency", "debt", "price", "news"]
    assert [q["status"] for q in rep["questions"]] == ["green", "green", "green", "amber", "green"]
    assert rep["label"] == {"code": "looks_solid", "display": "Looks solid"}
    for q in rep["questions"]:
        assert set(q) == {"id", "question", "status", "value_display", "meaning", "cites"}


def test_every_cite_points_at_a_real_fact_or_news_id_and_every_fact_has_a_source_link():
    rep = report.build_report("ABB", make_deps())
    valid = {f["id"] for f in rep["facts"]} | {n["id"] for n in rep["news"]}
    cites = [c for q in rep["questions"] for c in q["cites"]] + rep["overall"]["cites"] + rep["about"]["cites"]
    assert cites and set(cites) <= valid
    assert all(f["url"].startswith("https://") and f["source"] for f in rep["facts"])
    assert [f["id"] for f in rep["facts"]] == [f"F{i}" for i in range(1, len(rep["facts"]) + 1)]
    assert rep["facts"][-1]["label"].startswith("What the company does")


def test_ai_text_present_and_sources_listed():
    rep = report.build_report("ABB", make_deps())
    assert rep["ai_text"] is True
    assert rep["overall"]["text"].startswith("Sales grew about 12%")
    assert [(s["name"], s["ok"]) for s in rep["sources"]] == [
        ("Screener.in", True), ("Yahoo Finance", True), ("Google News", True)]
    assert rep["news"][0]["summary"] == "Summary of ABB India logs record orders."
    assert rep["news"][0]["url"].startswith("https://n.test/")


# ------------------------------------------------------------------ degraded sources
def test_screener_down_report_still_opens_with_grey_questions():
    def down(_):
        raise SourceUnavailable("Couldn't reach Screener.in right now.")

    rep = report.build_report("ABB", make_deps(screener=down))
    q = by_id(rep)
    assert all(q[k]["status"] == "grey" and q[k]["value_display"] == report.FETCH_FAILED
               for k in ("growth", "efficiency", "debt", "price"))
    assert q["news"]["status"] == "green"
    assert rep["ai_text"] is False and rep["overall"] == {"text": "", "cites": []}
    assert next(s for s in rep["sources"] if s["name"] == "Screener.in")["ok"] is False
    assert rep["price"]["display"] == "₹7,028.50"          # price still comes from yfinance


def test_screener_page_missing_or_unreadable_also_degrades():
    def boom(_):
        raise ValueError("parser blew up")

    for fn in (lambda s: (_ for _ in ()).throw(NotFound("none")), boom):
        rep = report.build_report("ABB", make_deps(screener=fn))
        assert by_id(rep)["growth"]["status"] == "grey"


def test_news_down_makes_only_the_news_question_grey():
    bad = lambda name: news_src.NewsResult(False, [], NOW, note="x")
    rep = report.build_report("ABB", make_deps(news=bad))
    q = by_id(rep)
    assert q["news"]["status"] == "grey" and q["news"]["value_display"] == report.FETCH_FAILED
    assert q["growth"]["status"] == "green" and rep["news"] == []
    assert next(s for s in rep["sources"] if s["name"] == "Google News")["ok"] is False


def test_news_future_that_raises_is_handled():
    def boom(_):
        raise RuntimeError("feed exploded")

    rep = report.build_report("ABB", make_deps(news=boom))
    assert by_id(rep)["news"]["status"] == "grey"


def test_price_falls_back_to_screener_and_footer_says_yahoo_failed():
    def fail(_):
        raise RuntimeError("yf")

    deps = make_deps(price=lambda s, fb, url: prices.fetch_price(s, fb, url, yf_fetch=fail))
    rep = report.build_report("ABB", deps)
    assert rep["price"]["display"] == "₹7,028" and rep["price"]["change_display"] == ""
    assert next(s for s in rep["sources"] if s["name"] == "Yahoo Finance")["ok"] is False


def test_no_ai_available_still_gives_a_full_fact_report():
    rep = report.build_report("ABB", make_deps(llm=None))
    assert rep["ai_text"] is False and rep["overall"]["text"] == "" and rep["about"]["text"] == ""
    assert len(rep["facts"]) >= 8
    q = by_id(rep)
    assert q["news"]["status"] == "grey" and "Couldn't check" in q["news"]["value_display"]
    assert rep["news"][0]["summary"] == "" and rep["news"][0]["tone"] == "neutral"
    assert q["growth"]["status"] == "green"


def test_writer_that_fails_the_check_falls_back_to_facts_only():
    bad_writer = lambda p: {"overall": {"text": "You should buy this [F1].", "cites": ["F1"]},
                            "about": {"text": "Makes things [F9].", "cites": ["F9"]}}
    rep = report.build_report("ABB", make_deps(llm=ScriptedLLM(all_neutral, bad_writer)))
    assert rep["ai_text"] is False and rep["overall"]["text"] == ""
    assert by_id(rep)["growth"]["status"] == "green"


def test_no_trusted_headlines_is_green_but_says_so_plainly():
    rep = report.build_report("ABB", make_deps(headlines=[]))
    q = by_id(rep)["news"]
    assert q["status"] == "green" and q["value_display"] == "No headlines from trusted outlets in the last 30 days."
    assert rep["news"] == []


# ------------------------------------------------------------------ news handling
def labels_for(spec):
    def fn(payload):
        rows = []
        for h in payload["headlines"]:
            about, tone, serious = spec.get(h["title"], ("yes", "neutral", "no"))
            rows.append({"id": h["id"], "about_company": about, "tone": tone, "serious": serious,
                         "summary": f"About: {h['title']}."})
        return {"labels": rows}
    return fn


def test_serious_news_turns_label_to_be_careful_and_is_shown_first():
    heads = [headline("Orders rise", 1), headline("Market round-up", 2), headline("Regulator fines company", 3),
             headline("Profit dips", 4), headline("New plant opens", 5)]
    spec = {"Orders rise": ("yes", "good", "no"), "Market round-up": ("no", "bad", "yes"),
            "Regulator fines company": ("yes", "bad", "yes"), "Profit dips": ("yes", "bad", "no")}
    rep = report.build_report("ABB", make_deps(headlines=heads, llm=ScriptedLLM(labels_for(spec), good_writer)))
    assert by_id(rep)["news"]["status"] == "red" and rep["label"]["code"] == "be_careful"
    serious = {n["title"]: n["serious"] for n in rep["news"]}
    assert serious == {"Regulator fines company": True, "Profit dips": False, "Orders rise": False}
    assert [n["title"] for n in rep["news"]] == ["Regulator fines company", "Profit dips", "Orders rise"]
    assert "Market round-up" not in [n["title"] for n in rep["news"]]   # not about the company
    assert by_id(rep)["news"]["cites"] == [n["id"] for n in rep["news"] if n["tone"] == "bad"]


def test_summary_with_advice_words_is_replaced_by_the_headline():
    heads = [headline("Orders rise", 1)]
    llm = ScriptedLLM(lambda p: {"labels": [{"id": "N1", "about_company": "yes", "tone": "good", "serious": "no",
                                             "summary": "Analysts say buy now."}]}, good_writer)
    rep = report.build_report("ABB", make_deps(headlines=heads, llm=llm))
    assert rep["news"][0]["summary"] == "Orders rise"


def test_loss_making_company_with_negative_net_worth_is_be_careful():
    rep = report.build_report("IDEA", make_deps(symbol="IDEA", llm=ScriptedLLM(all_neutral, lambda p: None)))
    q = by_id(rep)
    assert q["debt"]["status"] == "red" and q["price"]["status"] == "red"
    assert rep["label"]["code"] == "be_careful"


def test_empty_screener_shell_page_does_not_crash():
    rep = report.build_report("ABB", make_deps(symbol="GILLETTE"))
    assert by_id(rep)["efficiency"]["status"] == "grey" and by_id(rep)["price"]["status"] == "grey"


# ------------------------------------------------------------------ caching and storage
def test_get_report_saves_then_serves_from_cache_until_refresh():
    calls = []
    deps = make_deps(screener=lambda s: (calls.append(s), page("ABB"))[1])
    r1 = report.get_report("abb", deps=deps)
    r2 = report.get_report("ABB", deps=deps)
    assert r1 == r2 and calls == ["ABB"]
    report.get_report("ABB", refresh=True, deps=deps)
    assert calls == ["ABB", "ABB"]
    with connect() as conn:
        # a refresh inside the same second replaces the row (generated_at is part of the key)
        assert conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] >= 1
        assert conn.execute("SELECT label FROM reports LIMIT 1").fetchone()[0] == "looks_solid"
    assert report.latest_report("ABB")["symbol"] == "ABB"


def test_stale_cached_report_is_rebuilt():
    old = report.build_report("ABB", make_deps())
    old["generated_at"] = (datetime.now(prices.IST) - timedelta(hours=25)).isoformat(timespec="seconds")
    report._save(old)
    calls = []
    report.get_report("ABB", deps=make_deps(screener=lambda s: (calls.append(1), page("ABB"))[1]))
    assert calls == [1]


def test_failed_source_shows_when_it_last_worked():
    good = report.build_report("ABB", make_deps())
    good["generated_at"] = (datetime.now(prices.IST) - timedelta(hours=30)).isoformat(timespec="seconds")
    report._save(good)

    def down(_):
        raise SourceUnavailable("x")

    rep = report.build_report("ABB", make_deps(screener=down))
    entry = next(s for s in rep["sources"] if s["name"] == "Screener.in")
    assert entry["ok"] is False and entry["last_ok_display"] == good["sources"][0]["fetched_at_display"]


def test_unknown_symbol_is_not_found(monkeypatch):
    monkeypatch.setattr(nse, "refresh_companies", lambda force=False: 0)
    with pytest.raises(report.ApiError) as err:
        report.build_report("NOSUCH", make_deps())
    assert err.value.code == "not_found" and "NOSUCH" in err.value.message


# ------------------------------------------------------------------ HTTP endpoint
def test_report_endpoint_and_recent_list(monkeypatch):
    monkeypatch.setattr(nse, "refresh_companies", lambda force=False: 0)
    monkeypatch.setattr(report, "Deps", lambda: make_deps())
    with TestClient(app) as client:
        r = client.get("/api/reports/ABB")
        assert r.status_code == 200 and r.json()["label"]["code"] == "looks_solid"
        recent = client.get("/api/reports/recent").json()      # literal route must not be shadowed by {symbol}
        assert [x["symbol"] for x in recent] == ["ABB"] and recent[0]["label"] == "looks_solid"
        assert client.get("/api/reports/ABB", params={"refresh": "true"}).status_code == 200


def test_report_endpoint_errors(monkeypatch):
    monkeypatch.setattr(nse, "refresh_companies", lambda force=False: 0)
    monkeypatch.setattr(report, "Deps", lambda: make_deps())
    with TestClient(app) as client:
        r = client.get("/api/reports/NOSUCH")
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
        assert client.get("/api/reports/ABB", params={"refresh": "maybe"}).status_code == 400
