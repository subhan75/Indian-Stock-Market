from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

import pytest
import requests

from backend import app as _app  # noqa: F401
from backend.app import config
from backend.app.sources import news, prices

NOW = datetime(2026, 11, 25, 6, 0, tzinfo=timezone.utc)


def item(title, outlet, days_ago, link=None):
    when = format_datetime(NOW - timedelta(days=days_ago))
    link = link or f"https://news.google.com/rss/articles/{abs(hash((title, outlet)))}"
    return (f"<item><title>{escape(title)} - {escape(outlet)}</title><link>{escape(link)}</link>"
            f"<pubDate>{when}</pubDate><source url='https://x.test'>{escape(outlet)}</source></item>")


def rss(*items) -> bytes:
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>t</title>{''.join(items)}</channel></rss>".encode()


# ------------------------------------------------------------------ outlets
@pytest.mark.parametrize("raw,expected", [
    ("Economic Times", "Economic Times"), ("The Economic Times", "Economic Times"),
    ("Business Standard", "Business Standard"), ("Mint", "Mint"), ("Livemint", "Mint"),
    ("Moneycontrol", "Moneycontrol"), ("The Hindu BusinessLine", "The Hindu BusinessLine"),
    ("Financial Express", "Financial Express"), ("CNBC TV18", "CNBC-TV18"), ("cnbctv18.com", "CNBC-TV18"),
    ("Reuters", "Reuters"),
    ("Upstox", None), ("Multibagg AI", None), ("Mintgenie", None), ("", None),
])
def test_canonical_outlet(raw, expected):
    assert news.canonical_outlet(raw) == expected


def test_every_alias_maps_to_a_configured_trusted_outlet():
    assert set(news.ALIASES.values()) <= set(config.TRUSTED_OUTLETS)
    assert {news.canonical_outlet(n) for n in config.TRUSTED_OUTLETS} == set(config.TRUSTED_OUTLETS)


# ------------------------------------------------------------------ parsing
def test_keeps_only_trusted_outlets_and_strips_the_outlet_suffix():
    feed = rss(item("ABB India logs record orders", "Mint", 2), item("ABB option chain", "Upstox", 1))
    result = news.parse_feed(feed, NOW)
    assert [(h.title, h.outlet) for h in result] == [("ABB India logs record orders", "Mint")]


def test_drops_items_older_than_30_days_and_sorts_newest_first():
    feed = rss(item("Old story", "Mint", 45), item("Older", "Mint", 20), item("Newer", "Reuters", 1))
    assert [h.title for h in news.parse_feed(feed, NOW)] == ["Newer", "Older"]


def test_removes_duplicates_by_link_and_by_near_identical_title():
    feed = rss(
        item("ABB India Q2 net profit rises 12% on strong orders", "Mint", 3, link="https://a.test/1"),
        item("ABB India Q2 net profit rises 12% on strong orders", "Moneycontrol", 3, link="https://a.test/2"),
        item("ABB India Q2 net profit rises 12% on strong order", "Reuters", 4, link="https://a.test/3"),
        item("Different story about orders", "Mint", 5, link="https://a.test/1"),
        item("A completely different headline", "Business Standard", 6, link="https://a.test/4"),
    )
    titles = [h.title for h in news.parse_feed(feed, NOW)]
    assert titles == ["ABB India Q2 net profit rises 12% on strong orders", "A completely different headline"]


def test_headlines_that_merely_share_a_few_words_are_not_duplicates():
    feed = rss(item("ABB India Q2 profit rises 12%", "Mint", 3, link="https://a.test/1"),
               item("ABB India Q2 profit rises 12 percent", "Reuters", 4, link="https://a.test/3"))
    assert len(news.parse_feed(feed, NOW)) == 2


def test_caps_at_twenty_headlines():
    import random

    rng = random.Random(1)
    words = [" ".join("".join(rng.choices("abcdefghijklmnopqrstuvwxyz", k=7)) for _ in range(5)) for _ in range(40)]
    feed = rss(*[item(w, "Mint", 1 + i % 20, link=f"https://a.test/{i}") for i, w in enumerate(words)])
    assert len(news.parse_feed(feed, NOW)) == news.MAX_HEADLINES


def test_ignores_items_missing_date_link_or_title():
    feed = (b"<rss version='2.0'><channel><item><title>No date - Mint</title><link>https://a.test/1</link>"
            b"<source url='x'>Mint</source></item></channel></rss>")
    assert news.parse_feed(feed, NOW) == []


def test_date_display_is_indian_time():
    h = news.Headline("t", "Mint", datetime(2026, 11, 21, 20, 0, tzinfo=timezone.utc), "u")
    assert h.date_display == "22 Nov"  # 20:00 UTC is 01:30 IST the next day


def test_feed_url_quotes_company_name_and_asks_for_30_days():
    url = news.feed_url("M&M Financial Services Limited")
    assert url.startswith("https://news.google.com/rss/search?q=%22M%26M%20Financial")
    assert "+when:30d" in url and "hl=en-IN&gl=IN&ceid=IN:en" in url


# ------------------------------------------------------------------ fetching
class Resp:
    def __init__(self, status=200, content=b""):
        self.status_code, self.content = status, content


def test_fetch_news_ok_and_failures():
    ok = news.fetch_news("ABB India Limited", http_get=lambda u: Resp(200, rss(item("Story", "Mint", 1))), now=NOW)
    assert ok.ok and len(ok.headlines) == 1

    bad_status = news.fetch_news("ABB", http_get=lambda u: Resp(503))
    assert not bad_status.ok and bad_status.headlines == [] and "right now" in bad_status.note

    def boom(_):
        raise requests.ConnectionError("down")

    assert not news.fetch_news("ABB", http_get=boom).ok


def test_empty_feed_is_ok_with_no_headlines():
    result = news.fetch_news("Tiny Co", http_get=lambda u: Resp(200, rss()), now=NOW)
    assert result.ok and result.headlines == []


# ------------------------------------------------------------------ prices
def test_price_from_yfinance_with_change():
    r = prices.fetch_price("ABB", yf_fetch=lambda s: (7028.5, 6868.5))
    assert r.ok and r.source == "Yahoo Finance" and r.change_pct == pytest.approx(2.33)
    block = prices.price_block(r)
    assert block["display"] == "₹7,028.50" and block["change_display"] == "+2.3%" and block["direction"] == "up"


def test_price_falls_back_to_screener_without_change():
    def fail(_):
        raise RuntimeError("yfinance broke")

    r = prices.fetch_price("ABB", fallback_price=7028.0, fallback_url="https://s.test/ABB/", yf_fetch=fail)
    assert r.ok and r.source == "Screener.in" and r.change_pct is None and r.note
    block = prices.price_block(r)
    assert block["display"] == "₹7,028" and block["change_display"] == "" and block["direction"] == "flat"


def test_price_unavailable_when_everything_fails():
    def fail(_):
        raise RuntimeError("down")

    r = prices.fetch_price("ABB", yf_fetch=fail)
    assert not r.ok
    assert prices.price_block(r)["display"] == "Price unavailable"


def test_price_down_and_flat_directions_and_indian_grouping():
    down = prices.price_block(prices.fetch_price("X", yf_fetch=lambda s: (1234567.0, 1250000.0)))
    assert down["display"] == "₹12,34,567" and down["direction"] == "down" and down["change_display"] == "-1.2%"
    flat = prices.price_block(prices.fetch_price("X", yf_fetch=lambda s: (100.0, 100.0)))
    assert flat["direction"] == "flat" and flat["change_display"] == "+0.0%"


def test_format_time_uses_ist_and_12_hour_clock():
    assert prices.format_time(datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)) == "25 Nov, 3:30 pm"
    assert prices.format_time(datetime(2026, 11, 25, 4, 44, tzinfo=timezone.utc)) == "25 Nov, 10:14 am"
    assert prices.format_time(datetime(2026, 11, 25, 18, 30, tzinfo=timezone.utc)) == "26 Nov, 12:00 am"
