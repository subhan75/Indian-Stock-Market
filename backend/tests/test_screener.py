from pathlib import Path

import pytest
import requests

from backend.app.sources import screener
from backend.app.sources.base import NotFound, SourceUnavailable

FIX = Path(__file__).parent / "fixtures"


def parse(symbol: str):
    html = (FIX / f"{symbol}.html").read_text(encoding="utf-8")
    return screener.parse_company_page(
        html, symbol, f"https://www.screener.in/company/{symbol}/consolidated/", "2026-11-25T00:00:00+00:00"
    )


# ------------------------------------------------------------------ number parsing
@pytest.mark.parametrize("text,expected", [
    ("₹ 7,028", 7028.0), ("94.8", 94.8), ("29.9 %", 29.9), ("₹ -4.09", -4.09),
    ("-17%", -17.0), ("2,960,000 Total advances", 2960000.0), ("₹ Cr.", None), ("", None), (None, None),
])
def test_to_number(text, expected):
    assert screener.to_number(text) == expected


# ------------------------------------------------------------------ parsing real (trimmed) pages
def test_abb_top_ratios_and_text():
    d = parse("ABB")
    assert d.name == "ABB India Ltd"
    assert (d.price, d.pe, d.roce) == (7028.0, 94.8, 29.9)
    assert d.opm == 15.0
    assert d.broad_industry == "Electrical Equipment"
    assert d.industry == "Heavy Electrical Equipment"
    assert d.about.startswith("ABB India Limited is an integrated power equipment manufacturer")
    assert "[1]" not in d.about, "citation markers should be stripped"


def test_abb_quarters_are_last_eight_oldest_first():
    d = parse("ABB")
    assert d.quarter_labels[0] == "Dec 2024" and d.quarter_labels[-1] == "Sep 2026"
    assert d.sales == [3365.0, 3010.0, 2940.0, 3130.0, 3423.0, 3184.0, 3559.0, 3738.0]
    assert len(d.net_profit) == 8


def test_abb_balance_sheet_uses_latest_column():
    d = parse("ABB")
    assert (d.equity_capital, d.reserves, d.borrowings) == (42.0, 9297.0, 145.0)
    assert d.balance_as_of == "Jun 2026"
    assert d.has_deposits is False


def test_peers_exclude_self_and_median_is_computed_over_others():
    d = parse("ABB")
    assert "ABB" not in {p.symbol for p in d.peers}
    assert len(d.peers) == 6
    # Screener's own "Median" row includes the company itself (88.23); ours must not.
    assert d.median_peer_pe == pytest.approx(85.825)


def test_peers_with_negative_pe_are_ignored_in_median():
    d = parse("IDEA")
    assert any(p.pe is not None and p.pe < 0 for p in d.peers)
    assert d.median_peer_pe == pytest.approx(39.59)


def test_bank_page_uses_revenue_borrowing_and_deposits_rows():
    d = parse("HDFCBANK")
    assert d.has_deposits is True
    assert d.borrowings == 594144.0
    assert d.sales[-1] == 95132.0
    assert d.industry == "Private Sector Bank"
    # sector-specific peer columns: P/E must still be found by header text
    assert d.median_peer_pe == pytest.approx(18.455)


def test_loss_maker_has_blank_pe_and_negative_net_worth():
    d = parse("IDEA")
    assert d.pe is None and d.price == 11.7
    assert d.equity_capital + d.reserves < 0


def test_page_with_blank_top_ratios_parses_without_crashing():
    d = parse("GILLETTE")
    assert d.price is None and d.pe is None and d.roce is None
    assert d.peers == [] and d.median_peer_pe is None
    assert len(d.sales) == 8  # the tables are still there


def test_other_fixtures_parse():
    for sym in ("POLYCAB", "INFY", "BAJFINANCE"):
        d = parse(sym)
        assert d.price and d.pe and d.sales and d.borrowings is not None
        assert len(d.peers) >= 3


def test_too_few_peers_gives_no_median():
    d = parse("ABB")
    d.peers = d.peers[:2]
    assert d.median_peer_pe is None


# ------------------------------------------------------------------ fetching, caching, fallback
class FakeResponse:
    def __init__(self, status_code=200, text="<html></html>"):
        self.status_code = status_code
        self.text = text


class FakeHttp:
    def __init__(self, routes: dict[str, FakeResponse | Exception]):
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, url):
        self.calls.append(url)
        result = self.routes.get(url, FakeResponse(404))
        if isinstance(result, Exception):
            raise result
        return result


CONS = "https://www.screener.in/company/ABB/consolidated/"
STD = "https://www.screener.in/company/ABB/"
ABB_HTML = (FIX / "ABB.html").read_text(encoding="utf-8")


def test_fetch_uses_consolidated_and_caches_for_24h():
    http = FakeHttp({CONS: FakeResponse(200, ABB_HTML)})
    d1 = screener.fetch_company("abb", http_get=http)
    d2 = screener.fetch_company("ABB", http_get=http)
    assert d1.consolidated and d1.symbol == "ABB" and d1.pe == 94.8
    assert d2.pe == 94.8
    assert http.calls == [CONS], "second call must come from the cache"


def test_refresh_bypasses_cache():
    http = FakeHttp({CONS: FakeResponse(200, ABB_HTML)})
    screener.fetch_company("ABB", http_get=http)
    screener.fetch_company("ABB", refresh=True, http_get=http)
    assert http.calls == [CONS, CONS]


def test_falls_back_to_standalone_and_remembers_missing_consolidated():
    http = FakeHttp({CONS: FakeResponse(404), STD: FakeResponse(200, ABB_HTML)})
    d = screener.fetch_company("ABB", http_get=http)
    assert d.consolidated is False and d.url == STD
    screener.fetch_company("ABB", http_get=http)
    assert http.calls == [CONS, STD], "the 404 and the page are both cached"


def test_no_page_at_all_raises_not_found():
    with pytest.raises(NotFound):
        screener.fetch_company("ZZZZ", http_get=FakeHttp({}))


@pytest.mark.parametrize("bad", ["", "../etc", "A B", "X" * 30, "ABB/consolidated"])
def test_rejects_malformed_symbols_without_any_request(bad):
    http = FakeHttp({})
    with pytest.raises(NotFound):
        screener.fetch_company(bad, http_get=http)
    assert http.calls == []


def test_symbols_with_ampersand_are_url_encoded():
    http = FakeHttp({})
    with pytest.raises(NotFound):
        screener.fetch_company("M&M", http_get=http)
    assert http.calls[0] == "https://www.screener.in/company/M%26M/consolidated/"


def test_server_error_and_network_error_are_source_unavailable():
    with pytest.raises(SourceUnavailable):
        screener.fetch_company("ABB", http_get=FakeHttp({CONS: FakeResponse(503)}))
    with pytest.raises(SourceUnavailable):
        screener.fetch_company("ABB", http_get=FakeHttp({CONS: requests.ConnectionError("down")}))


def test_failed_fetch_is_not_cached():
    bad = FakeHttp({CONS: FakeResponse(503)})
    with pytest.raises(SourceUnavailable):
        screener.fetch_company("ABB", http_get=bad)
    good = FakeHttp({CONS: FakeResponse(200, ABB_HTML)})
    assert screener.fetch_company("ABB", http_get=good).pe == 94.8
