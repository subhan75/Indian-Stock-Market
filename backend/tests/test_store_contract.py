"""One set of checks that every Store implementation must pass:

  memory          InMemoryStore (used by the rest of the test suite)
  supabase-fake   the REAL supabase-py client talking to a small fake REST server (offline)
  supabase-real   the real client talking to a real Supabase TEST project. Runs only when these are set:
                  TEST_SUPABASE_URL, TEST_SUPABASE_PUBLISHABLE_KEY, TEST_USER_A_EMAIL, TEST_USER_A_PASSWORD,
                  TEST_USER_B_EMAIL, TEST_USER_B_PASSWORD   (use a separate, empty project, never your real one)
"""
import os
import uuid

import pytest
from postgrest.exceptions import APIError

from backend.app import config, store_supabase
from backend.app.store import REPORTS_KEPT_PER_STOCK, Conflict, InMemoryStore
from backend.app.store_supabase import SupabaseStore, make_client
from fake_postgrest import FakePostgrest

REAL_VARS = ["TEST_SUPABASE_URL", "TEST_SUPABASE_PUBLISHABLE_KEY", "TEST_USER_A_EMAIL", "TEST_USER_A_PASSWORD",
             "TEST_USER_B_EMAIL", "TEST_USER_B_PASSWORD"]
REAL_AVAILABLE = all(os.getenv(v) for v in REAL_VARS)
USER_A, USER_B = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))


class Backend:
    """Gives each test one or two users' stores on the same (fake or real) database."""

    def __init__(self, name, make_user_store, raw_client=None, cleanup=None):
        self.name, self.user_store, self.raw_client, self._cleanup = name, make_user_store, raw_client, cleanup

    def cleanup(self):
        if self._cleanup:
            self._cleanup()


@pytest.fixture(params=["memory", "supabase-fake",
                        pytest.param("supabase-real", marks=pytest.mark.skipif(
                            not REAL_AVAILABLE, reason="set the TEST_SUPABASE_* variables to run against Supabase"))])
def backend(request, monkeypatch):
    kind = request.param
    if kind == "memory":
        stores = {}
        yield Backend(kind, lambda who="a": stores.setdefault(who, InMemoryStore()))
        return
    monkeypatch.setattr(config, "SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_PUBLISHABLE_KEY", "sb_publishable_TEST")
    if kind == "supabase-fake":
        server = FakePostgrest()
        http = server.http_client()
        ids = {"a": USER_A, "b": USER_B}
        yield Backend(
            kind,
            lambda who="a": SupabaseStore(make_client(server.token_for(ids[who]), http=http), ids[who]),
            raw_client=lambda who=None: make_client(server.token_for(ids[who]) if who else None, http=http))
        return
    monkeypatch.setattr(config, "SUPABASE_URL", os.environ["TEST_SUPABASE_URL"].rstrip("/"))
    monkeypatch.setattr(config, "SUPABASE_PUBLISHABLE_KEY", os.environ["TEST_SUPABASE_PUBLISHABLE_KEY"])
    sessions = {}

    def session(who):
        if who not in sessions:
            auth = make_client().auth.sign_in_with_password({
                "email": os.environ[f"TEST_USER_{who.upper()}_EMAIL"],
                "password": os.environ[f"TEST_USER_{who.upper()}_PASSWORD"]})
            sessions[who] = (auth.session.access_token, auth.user.id)
        return sessions[who]

    def real_store(who="a"):
        token, uid = session(who)
        return SupabaseStore(make_client(token), uid)

    def wipe():
        for who in ("a", "b"):
            s = real_store(who)
            for h in s.holdings_list():
                s.holdings_delete(h["symbol"])
            for r in s.reports_latest_by_symbol(500):
                s._db.table("reports").delete().eq("user_id", s._user).eq("symbol", r["symbol"]).execute()

    wipe()
    yield Backend(kind, real_store, raw_client=lambda who=None: make_client(session(who)[0] if who else None),
                  cleanup=wipe)
    wipe()


@pytest.fixture
def supabase_only(backend):
    if backend.name == "memory":
        pytest.skip("row-level security only exists in the Supabase implementations")
    return backend


def hold(symbol="ABB", shares=10, price=100.5, watching=False, added="2026-11-25T10:00:00+05:30"):
    return {"symbol": symbol, "shares": shares, "buy_price": price, "watching": watching, "added_at": added}


def rep(symbol="ABB", when="2026-11-25T10:00:00+05:30", label="mixed", **extra):
    return {"symbol": symbol, "generated_at": when, "label": {"code": label, "display": label.title()}, **extra}


# ------------------------------------------------------------------ holdings
def test_holdings_round_trip_types_and_order(backend):
    s = backend.user_store()
    for sym in ("INFY", "ABB", "TITAN"):
        s.holdings_insert(hold(sym))
    rows = s.holdings_list()
    assert [r["symbol"] for r in rows] == ["INFY", "ABB", "TITAN"]
    assert rows[0] == {"symbol": "INFY", "shares": 10, "buy_price": 100.5, "watching": False,
                       "added_at": "2026-11-25T10:00:00+05:30"}
    assert isinstance(rows[0]["shares"], int) and isinstance(rows[0]["buy_price"], float)
    assert s.holdings_get("abb")["symbol"] == "ABB" and s.holdings_get("NOPE") is None


def test_a_watched_stock_has_no_shares_or_price(backend):
    s = backend.user_store()
    s.holdings_insert(hold("TITAN", None, None, True))
    row = s.holdings_get("TITAN")
    assert row["watching"] is True and row["shares"] is None and row["buy_price"] is None


def test_saving_a_stock_twice_is_a_conflict_and_changes_nothing(backend):
    s = backend.user_store()
    s.holdings_insert(hold("ABB", 10))
    with pytest.raises(Conflict):
        s.holdings_insert(hold("abb", 99))
    assert len(s.holdings_list()) == 1 and s.holdings_get("ABB")["shares"] == 10


def test_update_and_delete_say_whether_a_row_was_touched(backend):
    s = backend.user_store()
    s.holdings_insert(hold("ABB", 10, 100.5))
    assert s.holdings_update("abb", 20, 90.25, False) is True
    assert (s.holdings_get("ABB")["shares"], s.holdings_get("ABB")["buy_price"]) == (20, 90.25)
    assert s.holdings_update("NOPE", 1, 1.0, False) is False
    assert s.holdings_update("ABB", None, None, True) is True
    assert s.holdings_get("ABB")["watching"] is True and s.holdings_get("ABB")["shares"] is None
    assert s.holdings_delete("ABB") is True and s.holdings_delete("ABB") is False
    assert s.holdings_list() == []


# ------------------------------------------------------------------ reports
def test_reports_newest_first_and_limited(backend):
    s = backend.user_store()
    for day in (20, 25, 22):
        s.reports_save(rep(when=f"2026-11-{day}T10:00:00+05:30", label="mixed"))
    got = s.reports_recent("ABB", 2)
    assert [r["generated_at"][:10] for r in got] == ["2026-11-25", "2026-11-22"]
    assert s.reports_recent("abb", 1)[0]["generated_at"].startswith("2026-11-25")      # any case
    assert s.reports_recent("NOPE", 3) == []


def test_a_report_comes_back_exactly_as_saved(backend):
    s = backend.user_store()
    original = rep(price={"display": "₹7,028.50", "value": 7028.5}, questions=[{"id": "growth", "status": "green"}],
                   news=[], ai_text=False, nested={"a": [1, 2.5, None, True]})
    s.reports_save(original)
    assert s.reports_recent("ABB", 1) == [original]


def test_saving_the_same_second_replaces_instead_of_duplicating(backend):
    s = backend.user_store()
    s.reports_save(rep(label="mixed"))
    s.reports_save(rep(label="looks_solid"))
    got = s.reports_recent("ABB", 10)
    assert len(got) == 1 and got[0]["label"]["code"] == "looks_solid"


def test_only_the_newest_ten_reports_per_stock_are_kept(backend):
    s = backend.user_store()
    for day in range(1, 16):
        s.reports_save(rep(when=f"2026-11-{day:02d}T10:00:00+05:30"))
    s.reports_save(rep("INFY", when="2026-11-01T10:00:00+05:30"))
    kept = s.reports_recent("ABB", 50)
    assert len(kept) == REPORTS_KEPT_PER_STOCK
    assert kept[0]["generated_at"].startswith("2026-11-15") and kept[-1]["generated_at"].startswith("2026-11-06")
    assert len(s.reports_recent("INFY", 50)) == 1


def test_latest_by_symbol_is_one_row_per_stock_newest_first(backend):
    s = backend.user_store()
    s.reports_save(rep("ABB", "2026-11-20T10:00:00+05:30", "mixed"))
    s.reports_save(rep("ABB", "2026-11-25T10:00:00+05:30", "looks_solid"))
    s.reports_save(rep("INFY", "2026-11-22T10:00:00+05:30", "be_careful"))
    assert s.reports_latest_by_symbol(10) == [
        {"symbol": "ABB", "label": "looks_solid", "generated_at": "2026-11-25T10:00:00+05:30"},
        {"symbol": "INFY", "label": "be_careful", "generated_at": "2026-11-22T10:00:00+05:30"}]
    assert len(s.reports_latest_by_symbol(1)) == 1


# ------------------------------------------------------------------ Row Level Security (Supabase implementations)
def test_one_user_never_sees_another_users_rows(supabase_only):
    a, b = supabase_only.user_store("a"), supabase_only.user_store("b")
    a.holdings_insert(hold("ABB", 10))
    a.reports_save(rep("ABB"))
    assert b.holdings_list() == [] and b.holdings_get("ABB") is None
    assert b.reports_recent("ABB", 5) == [] and b.reports_latest_by_symbol(5) == []


def test_one_user_cannot_change_or_delete_another_users_rows(supabase_only):
    a, b = supabase_only.user_store("a"), supabase_only.user_store("b")
    a.holdings_insert(hold("ABB", 10, 100.5))
    assert b.holdings_update("ABB", 999, 1.0, False) is False
    assert b.holdings_delete("ABB") is False
    assert a.holdings_get("ABB")["shares"] == 10


def test_two_users_may_hold_the_same_stock(supabase_only):
    a, b = supabase_only.user_store("a"), supabase_only.user_store("b")
    a.holdings_insert(hold("ABB", 10))
    b.holdings_insert(hold("ABB", 5))
    assert a.holdings_get("ABB")["shares"] == 10 and b.holdings_get("ABB")["shares"] == 5


def test_a_user_cannot_write_a_row_that_belongs_to_someone_else(supabase_only):
    """Even by sending the other user's id: the row-level-security check rejects it."""
    raw = supabase_only.raw_client("b")
    victim_id = USER_A if supabase_only.name == "supabase-fake" else supabase_only.user_store("a")._user
    with pytest.raises(APIError) as err:
        raw.table("holdings").insert({"user_id": victim_id, "symbol": "EVIL", "shares": 1, "buy_price": 1.0,
                                      "watching": False, "added_at": "x"}).execute()
    assert err.value.code in {"42501", "PGRST301"}
    with pytest.raises(APIError):
        raw.table("reports").upsert({"user_id": victim_id, "symbol": "EVIL", "generated_at": "x",
                                     "label": "mixed", "report_json": {}},
                                    on_conflict="user_id,symbol,generated_at").execute()
    assert supabase_only.user_store("a").holdings_list() == []


def test_a_user_cannot_reassign_their_row_to_someone_else(supabase_only):
    a = supabase_only.user_store("a")
    a.holdings_insert(hold("ABB", 10))
    other = USER_B if supabase_only.name == "supabase-fake" else supabase_only.user_store("b")._user
    raw = supabase_only.raw_client("a")
    try:
        result = raw.table("holdings").update({"user_id": other}).eq("symbol", "ABB").execute()
        assert result.data == []                      # a WITH CHECK failure may also surface as an empty result
    except APIError as exc:
        assert exc.code in {"42501", "PGRST301"}
    assert a.holdings_get("ABB") is not None and supabase_only.user_store("b").holdings_get("ABB") is None


def test_without_signing_in_nothing_is_readable_or_writable(supabase_only):
    anon = supabase_only.raw_client(None)
    seen = []
    for table in ("holdings", "reports"):
        try:
            seen.append(anon.table(table).select("*").execute().data)
        except APIError as exc:
            assert exc.code == "42501"
            seen.append([])
    assert seen == [[], []]
    with pytest.raises(APIError):
        anon.table("holdings").insert({"user_id": USER_A, "symbol": "X", "shares": 1, "buy_price": 1.0,
                                       "watching": False, "added_at": "x"}).execute()
