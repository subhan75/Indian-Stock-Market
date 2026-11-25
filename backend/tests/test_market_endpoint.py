import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import config, holdings, marketday, report
from backend.app.main import app
from backend.app.sources import market as src
from backend.app.sources import news, nse

FIX = Path(__file__).parent / "fixtures"
RealDeps = marketday.MarketDeps       # tests monkeypatch marketday.MarketDeps, so keep the real class
NOW = datetime(2026, 11, 25, 14, 0, tzinfo=timezone.utc)
LEVELS = {"^NSEI": (25819.25, 25366.4), "^BSESN": (83938.28, 82435.99)}
FEED_FILES = {"ET Markets": "et_markets.xml", "Business Standard": "bs_markets.xml"}


class Counter:
    """Fake sources that count how often each one is called."""

    def __init__(self, down_indices=(), down_feeds=(), llm="default", raise_indices=False):
        self.index_calls = self.feed_calls = 0
        self.down_indices, self.down_feeds, self.raise_indices = set(down_indices), set(down_feeds), raise_indices
        self.llm = GoodLLM() if llm == "default" else llm

    def index(self, name, ticker, url):
        self.index_calls += 1
        if self.raise_indices:
            raise RuntimeError("index fake blew up")
        if name in self.down_indices:
            return src.IndexResult(name, url, False)
        last, prev = LEVELS[ticker]
        return src.IndexResult(name, url, True, last, round((last / prev - 1) * 100, 2))

    def feed(self, name, url):
        self.feed_calls += 1
        if name in self.down_feeds:
            return src.FeedResult(name, False, [])
        return src.FeedResult(name, True, news.parse_plain_feed((FIX / FEED_FILES[name]).read_bytes(), name, NOW))

    def deps(self):
        return RealDeps(index=self.index, feed=self.feed, llm=self.llm)


class GoodLLM:
    def __init__(self):
        self.calls = 0

    def complete_json(self, model, system, user):
        self.calls += 1
        return json.dumps({"points": [{"text": "Markets reacted to the overnight news [H1].", "cites": ["H1"]}]})


class RaisingLLM:
    def complete_json(self, model, system, user):
        from backend.app import ai
        raise ai.AiUnavailable("down")


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(config, "WRITER_MODEL", "big")
    monkeypatch.setattr(nse, "refresh_companies", lambda force=False: 0)
    monkeypatch.setattr(report, "get_report", lambda *a, **k: None)


def get(counter=None, refresh=False, now=NOW):
    counter = counter or Counter()
    return marketday.get_market(refresh=refresh, deps=counter.deps(), now=now)


def add_stock(symbol, name, watching=False):
    nse.store_companies([{"symbol": symbol, "name": name, "series": "EQ", "isin": symbol}])
    body = {"symbol": symbol, "watching": watching}
    if not watching:
        body.update(shares=10, buy_price=100.0)
    holdings.create(body)


def store_report(symbol, label):
    display = {"looks_solid": "Looks solid", "mixed": "Mixed", "be_careful": "Be careful"}[label]
    report._save({"symbol": symbol, "generated_at": "2026-11-25T10:00:00+05:30",
                  "label": {"code": label, "display": display}})


def source(page, name):
    return next(s for s in page["sources"] if s["name"] == name)


# ------------------------------------------------------------------ the full page
def test_full_page_matches_the_contract():
    page = get()
    assert set(page) == {"as_of", "indices", "points", "headlines", "your_stocks_in_news", "watching",
                         "sources", "ai_text", "disclaimer"}
    assert page["disclaimer"] == "Research aid, not financial advice."
    assert page["as_of"] == "25 Nov, 7:30 pm"                                  # 14:00 UTC in India time
    assert [i["name"] for i in page["indices"]] == ["Nifty 50", "Sensex"]
    nifty = page["indices"][0]
    assert nifty == {"name": "Nifty 50", "value_display": "25,819", "change_display": "+1.8%", "direction": "up",
                     "source": "Yahoo Finance", "url": "https://finance.yahoo.com/quote/%5ENSEI/"}
    assert page["ai_text"] is True and page["points"] == [
        {"text": "Markets reacted to the overnight news [H1].", "cites": ["H1"]}]
    assert [s["name"] for s in page["sources"]] == ["Yahoo Finance", "ET Markets", "Business Standard"]
    assert all(s["ok"] and re.match(r"\d{1,2} \w{3}, \d{1,2}:\d{2} [ap]m$", s["fetched_at_display"]) for s in page["sources"])


def test_headlines_are_the_ten_newest_across_both_outlets_with_sequential_ids():
    page = get()
    hs = page["headlines"]
    assert [h["id"] for h in hs] == [f"H{i}" for i in range(1, 11)]
    assert {h["outlet"] for h in hs} <= {"ET Markets", "Business Standard"}
    assert all(set(h) == {"id", "title", "outlet", "time_display", "url"} for h in hs)
    assert all(re.match(r"(\d{1,2} \w{3}, )?\d{1,2}:\d{2} [ap]m$", h["time_display"]) for h in hs)
    assert len({h["url"] for h in hs}) == 10
    pool = news.merge_headlines(*[src.FeedResult(n, True, news.parse_plain_feed((FIX / f).read_bytes(), n, NOW)).headlines
                                  for n, f in FEED_FILES.items()])
    assert [h["url"] for h in hs] == [h.url for h in pool[:10]]


def test_every_point_cites_a_headline_that_is_on_the_page():
    page = get()
    shown = {h["id"] for h in page["headlines"]}
    assert page["points"] and all(set(p["cites"]) <= shown for p in page["points"])


def test_ai_receives_exactly_the_ten_shown_headlines(monkeypatch):
    seen = {}

    def spy(llm, indices, headlines):
        seen.update(indices=indices, headlines=headlines)
        return [{"text": "Fine [H1].", "cites": ["H1"]}]

    monkeypatch.setattr("backend.app.ai.write_market_points", spy)
    page = get()
    assert [h["id"] for h in seen["headlines"]] == [h["id"] for h in page["headlines"]]
    assert [h["title"] for h in seen["headlines"]] == [h["title"] for h in page["headlines"]]
    assert seen["indices"][0] == {"name": "Nifty 50", "level": 25819, "change_percent": 1.79}


# ------------------------------------------------------------------ your stocks in the news and Watching
def test_a_stock_you_own_is_picked_up_when_it_is_in_the_headlines():
    add_stock("LGEINDIA", "LG Electronics India Limited")
    page = get()
    rows = [r for r in page["your_stocks_in_news"] if r["symbol"] == "LGEINDIA"]
    assert rows, "the fixture has a Business Standard headline about LG Electronics India"
    row = rows[0]
    assert set(row) == {"symbol", "name", "headline_id", "title", "outlet", "url", "report_url", "time_display"}
    assert "LG Electronics India" in row["title"] and row["report_url"] == "/report.html?symbol=LGEINDIA"
    shown = {h["url"]: h["id"] for h in page["headlines"]}
    assert row["headline_id"] == shown.get(row["url"])


def test_a_match_outside_the_top_ten_still_appears_with_no_headline_id():
    page = get()
    pool_urls = [h["url"] for h in page["headlines"]]
    pool = news.merge_headlines(*[news.parse_plain_feed((FIX / f).read_bytes(), n, NOW) for n, f in FEED_FILES.items()])
    outside = next(h for h in pool[10:] if h.url not in pool_urls and all(w.isalpha() for w in h.title.split()[:3]))
    add_stock("OUTSIDE", " ".join(outside.title.split()[:3]) + " Limited")      # its name is the headline's first words
    rows = [r for r in get()["your_stocks_in_news"] if r["url"] == outside.url]
    assert rows and rows[0]["headline_id"] is None and rows[0]["title"] == outside.title


def test_watching_lists_stocks_a_to_z_with_label_or_none_and_a_report_link():
    add_stock("TITAN", "Titan Company Limited", watching=True)
    add_stock("ABB", "ABB India Limited", watching=True)
    add_stock("INFY", "Infosys Limited")                          # owned: must not be in Watching
    store_report("TITAN", "looks_solid")
    page = get()
    assert page["watching"] == [
        {"symbol": "ABB", "name": "ABB India Limited", "label": None, "report_url": "/report.html?symbol=ABB"},
        {"symbol": "TITAN", "name": "Titan Company Limited", "label": {"code": "looks_solid", "display": "Looks solid"},
         "report_url": "/report.html?symbol=TITAN"}]


def test_no_saved_stocks_gives_empty_personal_blocks():
    page = get()
    assert page["your_stocks_in_news"] == [] and page["watching"] == []
    assert page["headlines"] and page["indices"]


# ------------------------------------------------------------------ degradation (spec 5.6)
def test_indices_down_keeps_headlines_and_points():
    page = get(Counter(down_indices={"Nifty 50", "Sensex"}))
    assert page["indices"] == [] and source(page, "Yahoo Finance")["ok"] is False
    assert len(page["headlines"]) == 10 and page["ai_text"] is True


def test_one_index_down_keeps_the_other_and_marks_yahoo_not_ok():
    page = get(Counter(down_indices={"Sensex"}))
    assert [i["name"] for i in page["indices"]] == ["Nifty 50"] and source(page, "Yahoo Finance")["ok"] is False


def test_one_feed_down_uses_the_other_feed_only():
    page = get(Counter(down_feeds={"ET Markets"}))
    assert {h["outlet"] for h in page["headlines"]} == {"Business Standard"}
    assert source(page, "ET Markets")["ok"] is False and source(page, "Business Standard")["ok"] is True


def test_both_feeds_down_means_no_headlines_no_points_no_ai_call():
    llm = GoodLLM()
    page = get(Counter(down_feeds={"ET Markets", "Business Standard"}, llm=llm))
    assert page["headlines"] == [] and page["points"] == [] and page["ai_text"] is False
    assert llm.calls == 0 and len(page["indices"]) == 2


def test_ai_unavailable_or_failing_leaves_the_headlines_and_numbers():
    for llm in (None, RaisingLLM()):
        page = get(Counter(llm=llm))
        assert page["points"] == [] and page["ai_text"] is False
        assert len(page["headlines"]) == 10 and len(page["indices"]) == 2


def test_sources_that_raise_instead_of_returning_are_survived():
    page = get(Counter(raise_indices=True))
    assert page["indices"] == [] and page["headlines"]
    assert marketday.get_market(deps=marketday.MarketDeps(
        index=lambda *a: (_ for _ in ()).throw(RuntimeError("x")),
        feed=lambda *a: (_ for _ in ()).throw(RuntimeError("y")), llm=None), refresh=True, now=NOW)["headlines"] == []


def test_everything_failing_returns_a_valid_empty_page():
    page = get(Counter(down_indices={"Nifty 50", "Sensex"}, down_feeds={"ET Markets", "Business Standard"}))
    assert page["indices"] == [] and page["headlines"] == [] and page["points"] == []
    assert [s["ok"] for s in page["sources"]] == [False, False, False]


# ------------------------------------------------------------------ caching (decision D9)
def test_a_second_request_within_fifteen_minutes_makes_no_source_or_ai_calls():
    c = Counter()
    get(c)
    assert (c.index_calls, c.feed_calls, c.llm.calls) == (2, 2, 1)
    get(c, now=NOW + timedelta(minutes=14))
    assert (c.index_calls, c.feed_calls, c.llm.calls) == (2, 2, 1)


def test_the_cache_expires_after_fifteen_minutes():
    c = Counter()
    get(c)
    get(c, now=NOW + timedelta(minutes=15, seconds=1))
    assert (c.index_calls, c.feed_calls, c.llm.calls) == (4, 4, 2)


def test_refresh_bypasses_and_replaces_the_cache():
    c = Counter()
    get(c)
    page = get(c, refresh=True, now=NOW + timedelta(minutes=2))
    assert (c.index_calls, c.feed_calls, c.llm.calls) == (4, 4, 2)
    get(c, now=NOW + timedelta(minutes=3))
    assert c.index_calls == 4                              # served from the refreshed cache
    assert page["as_of"] == "25 Nov, 7:32 pm"


def test_a_total_failure_is_not_cached_so_the_next_load_retries():
    bad = Counter(down_indices={"Nifty 50", "Sensex"}, down_feeds={"ET Markets", "Business Standard"})
    get(bad)
    good = Counter()
    page = get(good, now=NOW + timedelta(minutes=1))
    assert good.index_calls == 2 and len(page["headlines"]) == 10


def test_a_page_missing_all_indices_or_all_feeds_is_not_cached():
    get(Counter(down_indices={"Nifty 50", "Sensex"}))
    c = Counter()
    get(c, now=NOW + timedelta(minutes=1))
    assert c.index_calls == 2
    marketday._write_cache({"generated_at": NOW.isoformat(), "indices": [], "points": [], "pool": [], "sources": []},
                           NOW - timedelta(hours=1))
    get(Counter(down_feeds={"ET Markets", "Business Standard"}), refresh=True)
    c2 = Counter()
    get(c2, now=NOW + timedelta(minutes=1))
    assert c2.feed_calls == 2


def test_your_stocks_and_watching_are_fresh_even_when_the_market_part_is_cached():
    c = Counter()
    first = get(c)
    assert first["watching"] == []
    add_stock("TITAN", "Titan Company Limited", watching=True)
    second = get(c, now=NOW + timedelta(minutes=5))
    assert c.index_calls == 2                              # still cached
    assert [w["symbol"] for w in second["watching"]] == ["TITAN"]


def test_a_failed_source_shows_when_it_last_worked():
    get(Counter())
    later = NOW + timedelta(hours=1)
    page = get(Counter(down_feeds={"ET Markets"}), now=later, refresh=True)
    row = source(page, "ET Markets")
    assert row["ok"] is False and row["last_ok_display"] == "25 Nov, 7:30 pm"
    assert "last_ok_display" not in source(page, "Business Standard")


# ------------------------------------------------------------------ the HTTP endpoint
def test_endpoint_serves_the_page_and_rejects_a_bad_refresh_value(monkeypatch):
    now = datetime.now(timezone.utc)

    class Live(Counter):
        def feed(self, name, url):
            self.feed_calls += 1
            return src.FeedResult(name, True, [news.Headline(f"{name} story", name, now - timedelta(hours=1), f"https://{name}/1")])

    c = Live()
    monkeypatch.setattr(marketday, "MarketDeps", lambda: c.deps())
    with TestClient(app) as client:
        r = client.get("/api/market/today")
        assert r.status_code == 200 and r.json()["headlines"] and len(r.json()["indices"]) == 2
        assert client.get("/api/market/today", params={"refresh": "true"}).status_code == 200
        bad = client.get("/api/market/today", params={"refresh": "maybe"})
        assert bad.status_code == 400 and bad.json()["error"]["code"] == "bad_request"
