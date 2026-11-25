import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import pytest
import requests

from backend.app.sources import market, news, prices

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 25, 14, 0, tzinfo=timezone.utc)       # just after the fixtures were captured


def feed(name):
    return (FIX / name).read_bytes()


def rss(*items):
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>t</title>{''.join(items)}</channel></rss>".encode()


def item(title, link, hours_ago, desc="", when=None):
    stamp = format_datetime(when or (NOW - timedelta(hours=hours_ago)))
    return (f"<item><title>{title}</title><link>{link}</link><pubDate>{stamp}</pubDate>"
            f"<description><![CDATA[{desc}]]></description></item>")


# ------------------------------------------------------------------ real feed fixtures
def test_et_fixture_parses_into_clean_headlines():
    hs = news.parse_plain_feed(feed("et_markets.xml"), "ET Markets", NOW)
    assert len(hs) >= 8
    assert {h.outlet for h in hs} == {"ET Markets"}
    assert all(h.title and h.url.startswith("http") and h.published.tzinfo for h in hs)
    assert [h.published for h in hs] == sorted((h.published for h in hs), reverse=True)
    assert all("<" not in h.description and len(h.description) <= 200 for h in hs)
    assert all(NOW - timedelta(hours=24) <= h.published <= NOW for h in hs)


def test_business_standard_fixture_parses_and_keeps_its_descriptions():
    hs = news.parse_plain_feed(feed("bs_markets.xml"), "Business Standard", NOW)
    assert len(hs) == 12 and {h.outlet for h in hs} == {"Business Standard"}
    assert any(h.description for h in hs)


def test_window_excludes_old_items_and_a_later_clock_empties_the_feed():
    later = NOW + timedelta(days=3)
    assert news.parse_plain_feed(feed("et_markets.xml"), "ET Markets", later) == []
    earlier = NOW - timedelta(hours=4)
    kept = news.parse_plain_feed(feed("et_markets.xml"), "ET Markets", earlier)
    assert all(h.published <= earlier + timedelta(hours=1) for h in kept)


def test_window_hours_is_respected():
    feed_bytes = rss(item("New story", "https://a/1", 2), item("Day-old story", "https://a/2", 23),
                     item("Too old", "https://a/3", 25))
    titles = [h.title for h in news.parse_plain_feed(feed_bytes, "ET Markets", NOW)]
    assert titles == ["New story", "Day-old story"]
    assert [h.title for h in news.parse_plain_feed(feed_bytes, "ET Markets", NOW, window_hours=3)] == ["New story"]


def test_items_missing_a_date_link_or_title_are_dropped_without_error():
    xml = rss("<item><title>No date</title><link>https://a/1</link></item>",
              f"<item><title>No link</title><pubDate>{format_datetime(NOW)}</pubDate></item>",
              f"<item><link>https://a/3</link><pubDate>{format_datetime(NOW)}</pubDate></item>",
              item("Complete", "https://a/4", 1))
    assert [h.title for h in news.parse_plain_feed(xml, "ET Markets", NOW)] == ["Complete"]


def test_future_dated_items_are_ignored():
    assert news.parse_plain_feed(rss(item("From tomorrow", "https://a/1", 0, when=NOW + timedelta(days=1))),
                                 "ET Markets", NOW) == []


@pytest.mark.parametrize("raw,expected", [
    ("<p>Shares <b>rose</b> &amp; fell</p>", "Shares rose & fell"),
    ("  lots   of\n whitespace ", "lots of whitespace"),
    ("", ""),
    ("&lt;script&gt;alert(1)&lt;/script&gt;", "<script>alert(1)</script>"),   # entities become text, never markup
])
def test_clean_description(raw, expected):
    assert news.clean_description(raw) == expected


def test_clean_description_caps_length_with_an_ellipsis():
    out = news.clean_description("word " * 100)
    assert len(out) == 200 and out.endswith("…")


# ------------------------------------------------------------------ merging two feeds
def hl(title, url, hours_ago, outlet="ET Markets"):
    return news.Headline(title, outlet, NOW - timedelta(hours=hours_ago), url)


def test_merge_sorts_newest_first_and_removes_cross_feed_duplicates():
    et = [hl("Sensex ends 400 points higher as banks rally strongly", "https://et/1", 1),
          hl("Gold prices climb to a new record high on safe haven demand", "https://et/2", 3)]
    bs = [hl("Sensex ends 400 points higher as banks rally strongly", "https://bs/9", 1.1, "Business Standard"),
          hl("RBI keeps repo rate unchanged", "https://bs/2", 2, "Business Standard"),
          hl("Gold prices climb to a new record high on safe haven demand", "https://et/2", 3, "Business Standard")]
    merged = news.merge_headlines(et, bs)
    assert [h.url for h in merged] == ["https://et/1", "https://bs/2", "https://et/2"]
    assert merged[0].outlet == "ET Markets"       # the newer copy is kept... first seen wins on ties


def test_merge_handles_empty_inputs():
    assert news.merge_headlines() == [] and news.merge_headlines([], []) == []


def test_real_fixtures_merge_into_one_newest_first_list():
    et = news.parse_plain_feed(feed("et_markets.xml"), "ET Markets", NOW)
    bs = news.parse_plain_feed(feed("bs_markets.xml"), "Business Standard", NOW)
    merged = news.merge_headlines(et, bs)
    assert len(merged) >= len(et) and len({h.url for h in merged}) == len(merged)
    assert [h.published for h in merged] == sorted((h.published for h in merged), reverse=True)
    assert {h.outlet for h in merged} == {"ET Markets", "Business Standard"}


# ------------------------------------------------------------------ clock formatting
@pytest.mark.parametrize("when,now,expected", [
    (datetime(2026, 11, 25, 13, 40, tzinfo=timezone.utc), datetime(2026, 11, 25, 14, 0, tzinfo=timezone.utc), "7:10 pm"),
    (datetime(2026, 11, 24, 13, 40, tzinfo=timezone.utc), datetime(2026, 11, 25, 14, 0, tzinfo=timezone.utc), "24 Nov, 7:10 pm"),
    (datetime(2026, 11, 25, 18, 40, tzinfo=timezone.utc), datetime(2026, 11, 26, 5, 0, tzinfo=timezone.utc), "12:10 am"),
    (datetime(2026, 11, 25, 6, 30, tzinfo=timezone.utc), datetime(2026, 11, 25, 14, 0, tzinfo=timezone.utc), "12:00 pm"),
])
def test_format_clock_uses_indian_time(when, now, expected):
    assert prices.format_clock(when, now) == expected


# ------------------------------------------------------------------ fetching a feed
class Resp:
    def __init__(self, status=200, content=b""):
        self.status_code, self.content = status, content


def test_fetch_feed_ok_empty_feed_and_failures():
    ok = market.fetch_feed("ET Markets", "u", http_get=lambda u: Resp(200, feed("et_markets.xml")), now=NOW)
    assert ok.ok and ok.headlines and ok.name == "ET Markets"
    empty = market.fetch_feed("ET Markets", "u", http_get=lambda u: Resp(200, rss()), now=NOW)
    assert empty.ok and empty.headlines == []
    assert not market.fetch_feed("ET Markets", "u", http_get=lambda u: Resp(503)).ok

    def boom(_):
        raise requests.ConnectionError("down")

    assert not market.fetch_feed("ET Markets", "u", http_get=boom).ok


def test_the_configured_feeds_and_indices_match_the_locked_sources():
    assert dict(market.FEEDS) == {
        "ET Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "Business Standard": "https://www.business-standard.com/rss/markets-106.rss"}
    assert [(n, t) for n, t, _ in market.INDICES] == [("Nifty 50", "^NSEI"), ("Sensex", "^BSESN")]


# ------------------------------------------------------------------ indices
def test_fetch_index_success_and_change_against_previous_close():
    r = market.fetch_index("Nifty 50", "^NSEI", "https://y/nifty", quote=lambda t: (25819.25, 25366.4))
    assert r.ok and r.level == 25819.25 and r.change_pct == pytest.approx(1.79)
    assert market.index_block(r) == {"name": "Nifty 50", "value_display": "25,819", "change_display": "+1.8%",
                                     "direction": "up", "source": "Yahoo Finance", "url": "https://y/nifty"}


def test_index_without_previous_close_shows_a_level_but_no_change():
    r = market.fetch_index("Sensex", "^BSESN", "u", quote=lambda t: (83938.3, None))
    block = market.index_block(r)
    assert r.ok and block["change_display"] == "" and block["direction"] == "flat" and block["value_display"] == "83,938"


@pytest.mark.parametrize("last,prev,change,direction", [
    (24310, 24456, "-0.6%", "down"), (100.04, 100.0, "+0.0%", "flat"), (99.96, 100.0, "-0.0%", "flat"),
    (101, 100, "+1.0%", "up"),
])
def test_index_direction_and_sign(last, prev, change, direction):
    block = market.index_block(market.fetch_index("X", "^X", "u", quote=lambda t: (last, prev)))
    assert block["change_display"] == change and block["direction"] == direction


def test_fetch_index_failures_never_raise():
    def boom(_):
        raise RuntimeError("yahoo down")

    assert market.fetch_index("Nifty 50", "^NSEI", "u", quote=boom).ok is False

    def slow(_):
        time.sleep(0.5)
        return 1.0, 1.0

    started = time.time()
    assert market.fetch_index("Nifty 50", "^NSEI", "u", quote=slow, timeout=0.05).ok is False
    assert time.time() - started < 0.4          # gave up at the timeout, not after the slow call
