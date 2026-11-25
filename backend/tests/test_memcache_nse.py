import threading

import pytest
import requests

from backend.app import memcache
from backend.app.memcache import MemCache
from backend.app.sources import nse
from backend.app.sources.base import SourceUnavailable

CSV = """SYMBOL,NAME OF COMPANY, SERIES, ISIN NUMBER
ABB,ABB India Limited,EQ,INE117A01022
ABBOTINDIA,Abbott India Limited,EQ,INE358A01014
POLYCAB,Polycab India Limited,EQ,INE455K01017
SMEONLY,Some SME Ltd,SM,INE000000001
"""


# ------------------------------------------------------------------ MemCache
def test_memcache_get_put_and_default():
    c = MemCache()
    assert c.get("x") is None and c.get("x", "fallback") == "fallback"
    c.put("x", 1)
    assert c.get("x") == 1 and len(c) == 1
    c.clear()
    assert len(c) == 0


def test_memcache_evicts_the_least_recently_used_entry():
    c = MemCache(max_entries=3)
    for k in "abc":
        c.put(k, k)
    c.get("a")                         # touching a makes b the oldest
    c.put("d", "d")
    assert c.get("b") is None and {c.get("a"), c.get("c"), c.get("d")} == {"a", "c", "d"}
    assert len(c) == 3


def test_memcache_replaces_an_existing_key_without_growing():
    c = MemCache(max_entries=2)
    c.put("a", 1); c.put("a", 2)
    assert c.get("a") == 2 and len(c) == 1


def test_memcache_is_safe_under_concurrent_use():
    c = MemCache(max_entries=50)

    def work(n):
        for i in range(200):
            c.put(f"{n}-{i}", i)
            c.get(f"{n}-{i // 2}")

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(c) <= 50


def test_shared_caches_exist_and_clear_all_empties_them():
    memcache.pages.put("u", ("body", "t"))
    memcache.market.put("m", 1)
    memcache.clear_all()
    assert len(memcache.pages) == 0 and len(memcache.market) == 0


# ------------------------------------------------------------------ the NSE company list in memory
def test_parse_keeps_only_eq_and_be_series():
    assert {r["symbol"] for r in nse.parse_equity_csv(CSV)} == {"ABB", "ABBOTINDIA", "POLYCAB"}


def test_search_ranks_exact_symbol_then_symbol_prefix_then_name_prefix_then_contains():
    nse.store_companies(nse.parse_equity_csv(CSV) + [
        {"symbol": "ZZ1", "name": "Abb Holdings Limited", "series": "EQ", "isin": "x"},       # name starts with abb
        {"symbol": "ZZ2", "name": "Cabbage Farms Limited", "series": "EQ", "isin": "y"}])    # name contains abb
    assert [r["symbol"] for r in nse.search("abb")] == ["ABB", "ABBOTINDIA", "ZZ1", "ZZ2"]


def test_search_matches_any_case_trims_and_respects_the_limit():
    nse.store_companies(nse.parse_equity_csv(CSV))
    assert nse.search("  PolyCAB ")[0]["symbol"] == "POLYCAB"
    assert nse.search("india", limit=1) == [{"symbol": "ABB", "name": "ABB India Limited"}]
    assert nse.search("") == [] and nse.search("   ") == [] and nse.search("nomatchatall") == []


def test_search_returns_at_most_the_requested_number_of_results():
    nse.store_companies([{"symbol": f"S{i:02d}", "name": f"Sample {i}", "series": "EQ", "isin": ""} for i in range(30)])
    assert len(nse.search("sample", limit=10)) == 10


def test_get_company_ignores_case_and_unknown_symbols():
    nse.store_companies(nse.parse_equity_csv(CSV))
    assert nse.get_company("abb") == {"symbol": "ABB", "name": "ABB India Limited"}
    assert nse.get_company("NOPE") is None


def test_storing_companies_merges_and_updates_by_symbol():
    nse.store_companies([{"symbol": "ABB", "name": "Old Name", "series": "EQ", "isin": "1"}])
    nse.store_companies([{"symbol": "INFY", "name": "Infosys Limited", "series": "EQ", "isin": "2"},
                         {"symbol": "ABB", "name": "ABB India Limited", "series": "EQ", "isin": "1"}])
    assert nse.get_company("ABB")["name"] == "ABB India Limited" and nse.get_company("INFY") is not None


def test_staleness_follows_the_last_successful_load():
    assert nse.is_stale() and nse.last_updated() is None
    nse.store_companies(nse.parse_equity_csv(CSV))
    assert not nse.is_stale() and nse.last_updated() is not None


# ------------------------------------------------------------------ downloads, the snapshot fallback and retry throttling
class FakeResponse:
    def __init__(self, text="", status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def test_a_good_download_loads_the_list_and_is_not_the_snapshot(monkeypatch):
    monkeypatch.setattr(nse.requests, "get", lambda *a, **k: FakeResponse(CSV))
    assert nse.refresh_companies() == 3
    assert nse.get_company("ABB") and not nse.using_snapshot() and not nse.is_stale()


def test_a_fresh_list_is_not_downloaded_again(monkeypatch):
    calls = []
    monkeypatch.setattr(nse.requests, "get", lambda *a, **k: calls.append(1) or FakeResponse(CSV))
    nse.refresh_companies(); nse.refresh_companies()
    assert len(calls) == 1
    nse.refresh_companies(force=True)
    assert len(calls) == 2


@pytest.mark.parametrize("failure", [requests.ConnectionError("down"), FakeResponse("", 503), FakeResponse("garbage,only\n1,2")])
def test_a_failed_download_with_nothing_loaded_uses_the_bundled_snapshot(monkeypatch, failure):
    def get(*a, **k):
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(nse.requests, "get", get)
    assert nse.refresh_companies() == 0
    assert nse.using_snapshot() and nse.get_company("ABB") is not None and len(nse.search("india")) > 0
    assert nse.is_stale(), "a snapshot is never treated as a fresh download, so a real one is retried later"


def test_a_failed_download_keeps_the_list_already_in_memory(monkeypatch):
    nse.store_companies(nse.parse_equity_csv(CSV))
    monkeypatch.setattr(nse, "_updated_at", None)            # pretend it is stale
    monkeypatch.setattr(nse.requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("down")))
    assert nse.refresh_companies() == 0
    assert nse.get_company("POLYCAB") and not nse.using_snapshot()


def test_a_failing_download_is_not_retried_on_every_call(monkeypatch):
    calls = []

    def get(*a, **k):
        calls.append(1)
        raise requests.ConnectionError("down")

    monkeypatch.setattr(nse.requests, "get", get)
    nse.refresh_companies(); nse.refresh_companies(); nse.refresh_companies()
    assert len(calls) == 1, "one failure pauses further attempts for a while"
    nse.refresh_companies(force=True)
    assert len(calls) == 2, "but forcing a refresh always tries"


def test_with_no_download_and_no_snapshot_the_error_is_reported(monkeypatch):
    monkeypatch.setattr(nse, "SNAPSHOT_PATH", nse.SNAPSHOT_PATH.with_name("missing.csv"))
    monkeypatch.setattr(nse.requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("down")))
    with pytest.raises(SourceUnavailable, match="Couldn't fetch the NSE company list"):
        nse.refresh_companies()


def test_ensure_loaded_fills_an_empty_list_once_and_never_raises(monkeypatch):
    monkeypatch.setattr(nse.requests, "get", lambda *a, **k: FakeResponse(CSV))
    nse.ensure_loaded()
    assert nse.get_company("ABB")
    monkeypatch.setattr(nse.requests, "get", lambda *a, **k: pytest.fail("must not download when a list is loaded"))
    nse.ensure_loaded()
    nse.reset()
    monkeypatch.setattr(nse, "SNAPSHOT_PATH", nse.SNAPSHOT_PATH.with_name("missing.csv"))
    monkeypatch.setattr(nse.requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("x")))
    nse.ensure_loaded()                                     # no list at all: swallowed, not raised


def test_the_bundled_snapshot_is_a_real_list():
    rows = nse.parse_equity_csv(nse.SNAPSHOT_PATH.read_text(encoding="utf-8"))
    symbols = {r["symbol"] for r in rows}
    assert len(rows) > 2000 and {"ABB", "INFY", "RELIANCE", "HDFCBANK", "TITAN"} <= symbols
    assert all(r["name"] and r["series"] in {"EQ", "BE"} for r in rows)


def test_network_is_blocked_by_default_in_tests():
    with pytest.raises(requests.ConnectionError, match="blocked in tests"):
        requests.get("https://example.com")
