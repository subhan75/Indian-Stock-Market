import threading

import pytest

from backend.app import store
from backend.app.store import Conflict, InMemoryStore, NoStore


def hold(symbol="ABB", shares=10, price=100.0, watching=False, added="2026-11-25T10:00:00+05:30"):
    return {"symbol": symbol, "shares": shares, "buy_price": price, "watching": watching, "added_at": added}


def rep(symbol="ABB", when="2026-11-25T10:00:00+05:30", label="mixed", **extra):
    return {"symbol": symbol, "generated_at": when, "label": {"code": label, "display": label}, **extra}


# ------------------------------------------------------------------ holdings
def test_holdings_round_trip_in_insertion_order():
    s = InMemoryStore()
    for sym in ("INFY", "ABB", "TITAN"):
        s.holdings_insert(hold(sym))
    assert [h["symbol"] for h in s.holdings_list()] == ["INFY", "ABB", "TITAN"]
    assert s.holdings_get("abb")["symbol"] == "ABB"          # lookups ignore case
    assert s.holdings_get("NOPE") is None


def test_the_same_symbol_twice_is_a_conflict_whatever_the_case():
    s = InMemoryStore()
    s.holdings_insert(hold("ABB"))
    with pytest.raises(Conflict):
        s.holdings_insert(hold("abb"))
    assert len(s.holdings_list()) == 1


def test_update_and_delete_report_whether_anything_changed():
    s = InMemoryStore()
    s.holdings_insert(hold("ABB", 10, 100.0))
    assert s.holdings_update("abb", 20, 90.5, False) is True
    assert (s.holdings_get("ABB")["shares"], s.holdings_get("ABB")["buy_price"]) == (20, 90.5)
    assert s.holdings_update("NOPE", 1, 1.0, False) is False
    assert s.holdings_update("ABB", None, None, True) is True and s.holdings_get("ABB")["watching"] is True
    assert s.holdings_delete("ABB") is True and s.holdings_delete("ABB") is False


def test_returned_rows_are_copies_so_callers_cannot_change_stored_data():
    s = InMemoryStore()
    s.holdings_insert(hold("ABB"))
    s.holdings_list()[0]["shares"] = 999
    s.holdings_get("ABB")["shares"] = 999
    assert s.holdings_get("ABB")["shares"] == 10
    s.reports_save(rep())
    s.reports_recent("ABB", 1)[0]["label"] = "tampered"
    assert s.reports_recent("ABB", 1)[0]["label"] == {"code": "mixed", "display": "mixed"}


# ------------------------------------------------------------------ reports
def test_reports_come_back_newest_first_and_limited():
    s = InMemoryStore()
    for day in (20, 25, 22):
        s.reports_save(rep(when=f"2026-11-{day}T10:00:00+05:30"))
    got = s.reports_recent("ABB", 2)
    assert [r["generated_at"][:10] for r in got] == ["2026-11-25", "2026-11-22"]
    assert s.reports_recent("NOPE", 2) == []


def test_saving_the_same_second_replaces_instead_of_duplicating():
    s = InMemoryStore()
    s.reports_save(rep(label="mixed"))
    s.reports_save(rep(label="looks_solid"))
    assert len(s.reports_recent("ABB", 10)) == 1 and s.reports_recent("ABB", 1)[0]["label"]["code"] == "looks_solid"


def test_only_the_newest_ten_reports_per_stock_are_kept():
    s = InMemoryStore()
    for day in range(1, 16):
        s.reports_save(rep(when=f"2026-11-{day:02d}T10:00:00+05:30"))
    s.reports_save(rep("INFY", when="2026-11-01T10:00:00+05:30"))
    kept = s.reports_recent("ABB", 50)
    assert len(kept) == store.REPORTS_KEPT_PER_STOCK == 10
    assert kept[-1]["generated_at"].startswith("2026-11-06") and kept[0]["generated_at"].startswith("2026-11-15")
    assert len(s.reports_recent("INFY", 50)) == 1                       # another stock is untouched


def test_latest_by_symbol_is_one_row_per_stock_newest_first():
    s = InMemoryStore()
    s.reports_save(rep("ABB", "2026-11-20T10:00:00+05:30", "mixed"))
    s.reports_save(rep("ABB", "2026-11-25T10:00:00+05:30", "looks_solid"))
    s.reports_save(rep("INFY", "2026-11-22T10:00:00+05:30", "be_careful"))
    assert s.reports_latest_by_symbol(10) == [
        {"symbol": "ABB", "label": "looks_solid", "generated_at": "2026-11-25T10:00:00+05:30"},
        {"symbol": "INFY", "label": "be_careful", "generated_at": "2026-11-22T10:00:00+05:30"}]
    assert len(s.reports_latest_by_symbol(1)) == 1


def test_two_users_stores_are_completely_separate():
    a, b = InMemoryStore(), InMemoryStore()
    a.holdings_insert(hold("ABB"))
    a.reports_save(rep())
    assert b.holdings_list() == [] and b.reports_recent("ABB", 5) == [] and b.reports_latest_by_symbol(5) == []


def test_concurrent_inserts_of_one_symbol_let_exactly_one_win():
    s = InMemoryStore()
    results = []

    def attempt():
        try:
            s.holdings_insert(hold("ABB"))
            results.append("ok")
        except Conflict:
            results.append("conflict")

    threads = [threading.Thread(target=attempt) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 1 and results.count("conflict") == 11


# ------------------------------------------------------------------ which store is current
def test_current_returns_the_store_for_this_request_and_nothing_leaks_after(isolated):
    mine = InMemoryStore()
    assert store.current() is isolated                                   # the test default
    with store.use(mine):
        assert store.current() is mine
    assert store.current() is isolated


def test_bind_and_unbind_for_the_request_guard():
    mine = InMemoryStore()
    token = store.bind(mine)
    assert store.current() is mine
    store.unbind(token)
    assert store.current() is not mine


def test_without_any_store_using_saved_data_fails_loudly(monkeypatch):
    monkeypatch.setattr(store, "_test_fallback", None)
    with pytest.raises(NoStore):
        store.current()


def test_a_store_set_in_one_context_is_not_seen_by_a_new_thread_unless_bound_there(monkeypatch):
    """Documents why code must not use the store from threads it starts itself."""
    monkeypatch.setattr(store, "_test_fallback", None)
    mine = InMemoryStore()
    seen = {}
    with store.use(mine):
        t = threading.Thread(target=lambda: seen.update(found=_has_store()))
        t.start(); t.join()
    assert seen["found"] is False


def _has_store():
    try:
        store.current()
        return True
    except NoStore:
        return False


def test_the_shared_test_store_can_only_be_installed_inside_pytest(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    with pytest.raises(RuntimeError, match="tests only"):
        store.install_test_store(InMemoryStore())
    store.install_test_store(None)                                       # clearing is always allowed
