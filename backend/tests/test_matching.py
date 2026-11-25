from datetime import datetime, timedelta, timezone

import pytest

from backend.app import config
from backend.app.matching import build_matcher, find_stock_news, name_stem
from backend.app.sources.news import Headline

STOCKS = {
    "ABB": "ABB India Limited", "BAJFINANCE": "Bajaj Finance Limited", "TATAMOTORS": "Tata Motors Limited",
    "TATASTEEL": "Tata Steel Limited", "INFY": "Infosys Limited", "HINDUNILVR": "Hindustan Unilever Limited",
    "ITC": "ITC Limited", "IDEA": "Vodafone Idea Limited", "TITAN": "Titan Company Limited",
    "RELIANCE": "Reliance Industries Limited", "SBIN": "State Bank of India", "HDFCBANK": "HDFC Bank Limited",
    "M&M": "Mahindra & Mahindra Limited",
}


def matches(symbol, title):
    return build_matcher(symbol, STOCKS[symbol]).matches(title)


# ------------------------------------------------------------------ name stems
@pytest.mark.parametrize("name,stem", [
    ("ABB India Limited", "abb india"), ("Bajaj Finance Limited", "bajaj finance"),
    ("Titan Company Limited", "titan"), ("ITC Limited", "itc"), ("State Bank of India", "state bank of india"),
    ("Vodafone Idea Ltd.", "vodafone idea"), ("Foo Corporation Limited", "foo"),
    ("Something (India) Limited", "something"), ("Mahindra & Mahindra Limited", "mahindra & mahindra"),
])
def test_name_stem(name, stem):
    assert name_stem(name) == stem


# ------------------------------------------------------------------ headlines that must match
TRUE_MATCHES = [
    ("ABB", "ABB India logs record Q3 orders, up 56%"),
    ("ABB", "ABB shares jump after strong results"),                      # all-caps ticker
    ("INFY", "Infosys's results beat street estimates"),                  # possessive
    ("INFY", "INFOSYS raises revenue guidance"),                          # name in capitals
    ("BAJFINANCE", "Bajaj Finance Q2 profit rises 12%"),
    ("TATAMOTORS", "Tata Motors cuts prices of passenger cars"),
    ("TATASTEEL", "Tata Steel to invest ₹5,000 crore in new plant"),
    ("ITC", "ITC hotels demerger: what changes for shareholders"),        # short name, matched by ticker
    ("IDEA", "IDEA shares surge on AGR relief"),
    ("IDEA", "Vodafone Idea seeks fresh funding from banks"),
    ("TITAN", "Titan jewellery sales up 18% in festive quarter"),
    ("RELIANCE", "Reliance Industries Q2 profit beats estimates"),
    ("SBIN", "State Bank of India raises lending rates"),
    ("HDFCBANK", "HDFC Bank, ICICI Bank among top gainers"),
    ("HINDUNILVR", "HINDUNILVR slips 2% after margin warning"),
    ("ABB", "Power stocks: abb  india   leads the rally"),               # irregular spacing and case
]


@pytest.mark.parametrize("symbol,title", TRUE_MATCHES)
def test_true_matches(symbol, title):
    assert matches(symbol, title), title


# ------------------------------------------------------------------ look-alikes that must NOT match
FALSE_MATCHES = [
    ("BAJFINANCE", "Bajaj Finserv Q2 profit rises 9%"),                   # the sibling company
    ("TATAMOTORS", "Tata Steel plans new plant in Odisha"),
    ("TATASTEEL", "Tata Motors launches new EV"),
    ("HINDUNILVR", "HUL launches new soap range"),                        # alias, not matched in v0 (D7)
    ("SBIN", "SBI hikes lending rates by 25 bps"),                        # alias, not matched in v0 (D7)
    ("IDEA", "It is not a good idea for investors to chase rallies"),     # the English word
    ("TITAN", "Titanic-themed ETF launches"),                             # longer word
    ("RELIANCE", "India's reliance on imported oil grows"),               # the English word
    ("ABB", "ABBOTT India shares rally"),                                 # ticker inside a longer name
    ("INFY", "Infosystems Ltd gains on order win"),                       # stem inside a longer word
    ("ITC", "ITCs of the world are consolidating"),                       # ticker followed by a letter
    ("HDFCBANK", "HDFC banking sector outlook improves"),                 # stem + 'ing'
    ("IDEA", "Vodafone launches 5G in three more cities"),                # partial name
    ("ITC", "The itc sector report"),                                     # lower-case ticker
    ("M&M", "Mahindra Lifespace posts record sales"),                     # different Mahindra company
]


@pytest.mark.parametrize("symbol,title", FALSE_MATCHES)
def test_look_alikes_do_not_match(symbol, title):
    assert not matches(symbol, title), title


def test_the_test_set_is_big_enough():
    assert len(TRUE_MATCHES) >= 10 and len(FALSE_MATCHES) >= 10


def test_symbols_with_symbols_have_no_ticker_matcher_and_short_stems_are_skipped():
    m = build_matcher("M&M", "Mahindra & Mahindra Limited")
    assert m.ticker is None and m.stem is not None
    itc = build_matcher("ITC", "ITC Limited")
    assert itc.stem is None and itc.ticker is not None                    # stem 'itc' is under 4 characters
    assert build_matcher("ZZ", "ZZ Limited").ticker is None               # tickers under 3 letters are ignored


# ------------------------------------------------------------------ building the rows
NOW = datetime(2026, 11, 25, 14, 0, tzinfo=timezone.utc)


def hl(title, minutes_ago, url=None, outlet="ET Markets"):
    return Headline(title, outlet, NOW - timedelta(minutes=minutes_ago), url or f"https://h/{abs(hash(title))}")


def stocks(*symbols):
    return [{"symbol": s, "name": STOCKS[s]} for s in symbols]


def test_rows_carry_the_fields_the_page_needs_and_link_to_the_report():
    pool = [hl("Titan jewellery sales up", 5, "https://h/1")]
    rows = find_stock_news(stocks("TITAN"), pool, {"https://h/1": "H1"})
    assert rows == [{"symbol": "TITAN", "name": "Titan Company Limited", "headline_id": "H1",
                     "title": "Titan jewellery sales up", "outlet": "ET Markets", "url": "https://h/1",
                     "report_url": "/report.html?symbol=TITAN"}]


def test_headline_id_is_none_when_the_headline_is_not_among_those_shown():
    pool = [hl("Titan jewellery sales up", 5, "https://h/1")]
    assert find_stock_news(stocks("TITAN"), pool, {})[0]["headline_id"] is None


def test_a_headline_naming_two_of_your_stocks_gives_one_row_each():
    pool = [hl("Tata Motors and Tata Steel lead the rally", 5, "https://h/1")]
    rows = find_stock_news(stocks("TATAMOTORS", "TATASTEEL"), pool, {})
    assert sorted(r["symbol"] for r in rows) == ["TATAMOTORS", "TATASTEEL"]


def test_no_stocks_or_no_headlines_gives_no_rows():
    assert find_stock_news([], [hl("Titan up", 1)], {}) == []
    assert find_stock_news(stocks("TITAN"), [], {}) == []
    assert find_stock_news(stocks("TITAN"), [hl("Nothing relevant here", 1)], {}) == []


def test_at_most_three_headlines_per_stock_keeping_the_newest():
    pool = [hl(f"Titan story number {i}", i + 1, f"https://h/{i}") for i in range(6)]        # newest first
    rows = find_stock_news(stocks("TITAN"), pool, {})
    assert [r["url"] for r in rows] == ["https://h/0", "https://h/1", "https://h/2"]


def test_at_most_ten_rows_overall_newest_first_across_stocks(monkeypatch):
    pool = []
    for i in range(5):
        pool.append(hl(f"Titan story {i}", i * 2 + 1, f"https://h/t{i}"))
        pool.append(hl(f"Infosys story {i}", i * 2 + 2, f"https://h/i{i}"))
        pool.append(hl(f"ABB India story {i}", i * 2 + 3, f"https://h/a{i}"))
    pool.sort(key=lambda h: h.published, reverse=True)
    rows = find_stock_news(stocks("TITAN", "INFY", "ABB"), pool, {})
    assert len(rows) == 9                                                   # 3 stocks x 3 each, under the cap of 10
    monkeypatch.setattr(config, "MATCH_MAX_TOTAL", 4)
    capped = find_stock_news(stocks("TITAN", "INFY", "ABB"), pool, {})
    assert len(capped) == 4
    times = [next(h.published for h in pool if h.url == r["url"]) for r in capped]
    assert times == sorted(times, reverse=True)


def test_watching_and_owned_stocks_are_treated_the_same():
    pool = [hl("Infosys wins a big deal", 3, "https://h/1")]
    assert len(find_stock_news(stocks("INFY"), pool, {})) == 1
