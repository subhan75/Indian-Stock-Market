import pytest
from fastapi.testclient import TestClient

from backend.app import config, report
from backend.app.main import app
from backend.app.sources import nse

COMPANIES = [
    {"symbol": "ABB", "name": "ABB India Limited", "series": "EQ", "isin": "a"},
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance Limited", "series": "EQ", "isin": "b"},
    {"symbol": "M&M", "name": "Mahindra & Mahindra Limited", "series": "EQ", "isin": "c"},
    {"symbol": "TITAN", "name": "Titan Company Limited", "series": "EQ", "isin": "d"},
]


@pytest.fixture
def client(monkeypatch):
    nse.store_companies(COMPANIES)
    monkeypatch.setattr(nse, "refresh_companies", lambda force=False: 0)  # never touch the network
    built = []
    monkeypatch.setattr(report, "get_report", lambda symbol, refresh=False, deps=None: built.append(symbol))
    with TestClient(app) as c:
        c.built = built
        yield c


def err(resp, status, code, message):
    assert resp.status_code == status, resp.text
    assert resp.json() == {"error": {"code": code, "message": message}}


HOLD = {"symbol": "ABB", "shares": 50, "buy_price": 720.5, "watching": False}


# ------------------------------------------------------------------ create
def test_create_holding_returns_saved_row_and_builds_a_report(client):
    r = client.post("/api/holdings", json=HOLD)
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"symbol", "name", "watching", "shares", "buy_price", "added_at"}
    assert body["symbol"] == "ABB" and body["name"] == "ABB India Limited"
    assert body["shares"] == 50 and body["buy_price"] == 720.5 and body["watching"] is False
    assert body["added_at"].endswith("+05:30")
    assert client.built == ["ABB"]


def test_symbol_is_trimmed_and_uppercased_and_ampersand_works(client):
    assert client.post("/api/holdings", json={**HOLD, "symbol": " abb "}).json()["symbol"] == "ABB"
    assert client.post("/api/holdings", json={**HOLD, "symbol": "m&m"}).json()["symbol"] == "M&M"


def test_buy_price_is_rounded_to_two_decimals_and_integers_are_accepted(client):
    assert client.post("/api/holdings", json={**HOLD, "buy_price": 720.456}).json()["buy_price"] == 720.46
    assert client.post("/api/holdings", json={**HOLD, "symbol": "TITAN", "buy_price": 3000}).json()["buy_price"] == 3000.0


def test_watching_stores_no_shares_or_price_even_if_sent(client):
    r = client.post("/api/holdings", json={"symbol": "TITAN", "watching": True, "shares": 10, "buy_price": 5})
    assert r.status_code == 201
    assert r.json()["shares"] is None and r.json()["buy_price"] is None and r.json()["watching"] is True
    assert client.post("/api/holdings", json={"symbol": "ABB", "watching": True}).status_code == 201


def test_report_failure_never_fails_the_save(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("everything is down")

    monkeypatch.setattr(report, "get_report", boom)
    assert client.post("/api/holdings", json=HOLD).status_code == 201


# ------------------------------------------------------------------ validation catalogue
@pytest.mark.parametrize("symbol", ["", "A B", "../x", "X" * 21, "ABB/1", 5, ["ABB"]])
def test_bad_symbol(client, symbol):
    r = client.post("/api/holdings", json={**HOLD, "symbol": symbol})
    err(r, 400, "bad_request", "That doesn't look like an NSE symbol.")


def test_missing_symbol(client):
    err(client.post("/api/holdings", json={"shares": 1, "buy_price": 1}), 400, "bad_request",
        "That doesn't look like an NSE symbol.")


def test_symbol_not_on_the_nse_list(client):
    err(client.post("/api/holdings", json={**HOLD, "symbol": "NOSUCH"}), 404, "not_found",
        "NOSUCH isn't on the NSE equity list. Check the symbol or search by company name.")


@pytest.mark.parametrize("shares", [None, 0, -5, 10.5, 50.0, "50", True, [], {}])
def test_bad_shares(client, shares):
    body = {**HOLD, "shares": shares}
    err(client.post("/api/holdings", json=body), 400, "bad_request",
        "Enter the number of shares as a whole number, 1 or more.")


def test_missing_shares_key(client):
    body = {k: v for k, v in HOLD.items() if k != "shares"}
    err(client.post("/api/holdings", json=body), 400, "bad_request",
        "Enter the number of shares as a whole number, 1 or more.")


def test_too_many_shares(client):
    err(client.post("/api/holdings", json={**HOLD, "shares": config.MAX_SHARES + 1}), 400, "bad_request",
        "That number of shares looks too large. Check it.")
    assert client.post("/api/holdings", json={**HOLD, "shares": config.MAX_SHARES}).status_code == 201


@pytest.mark.parametrize("price", [None, 0, -1, "720", True, 0.004, config.MAX_BUY_PRICE + 1, float("nan")])
def test_bad_buy_price(client, price):
    body = {**HOLD, "buy_price": price}
    r = client.post("/api/holdings", content=__import__("json").dumps(body, allow_nan=True),
                    headers={"Content-Type": "application/json"})
    err(r, 400, "bad_request", "Enter your average buy price in rupees, more than 0.")


def test_non_boolean_watching_and_non_object_body_are_generic_errors(client):
    err(client.post("/api/holdings", json={**HOLD, "watching": "yes"}), 400, "bad_request", "That request wasn't valid.")
    err(client.post("/api/holdings", json=[HOLD]), 400, "bad_request", "That request wasn't valid.")
    err(client.post("/api/holdings", content="not json", headers={"Content-Type": "application/json"}),
        400, "bad_request", "That request wasn't valid.")


def test_duplicate_symbol(client):
    client.post("/api/holdings", json=HOLD)
    err(client.post("/api/holdings", json={**HOLD, "symbol": "abb"}), 400, "bad_request",
        "You already have ABB. Edit it instead.")


def test_holdings_limit(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_HOLDINGS", 2)
    client.post("/api/holdings", json=HOLD)
    client.post("/api/holdings", json={**HOLD, "symbol": "TITAN"})
    err(client.post("/api/holdings", json={**HOLD, "symbol": "BAJFINANCE"}), 400, "bad_request",
        "You can keep up to 2 stocks in v0.")


def test_failed_validation_saves_nothing(client):
    client.post("/api/holdings", json={**HOLD, "shares": 0})
    assert client.built == []
    from backend.app import holdings
    assert holdings.list_holdings() == []


# ------------------------------------------------------------------ update
def test_update_changes_fields_and_keeps_added_at(client):
    first = client.post("/api/holdings", json=HOLD).json()
    r = client.put("/api/holdings/ABB", json={"symbol": "ABB", "shares": 80, "buy_price": 700, "watching": False})
    assert r.status_code == 200
    assert (r.json()["shares"], r.json()["buy_price"]) == (80, 700.0)
    assert r.json()["added_at"] == first["added_at"]


def test_update_body_symbol_is_optional_and_case_insensitive(client):
    client.post("/api/holdings", json=HOLD)
    assert client.put("/api/holdings/abb", json={"shares": 5, "buy_price": 9}).json()["shares"] == 5
    assert client.put("/api/holdings/ABB", json={"symbol": "abb", "shares": 6, "buy_price": 9}).status_code == 200


def test_update_symbol_mismatch(client):
    client.post("/api/holdings", json=HOLD)
    err(client.put("/api/holdings/ABB", json={**HOLD, "symbol": "TITAN"}), 400, "bad_request",
        "The symbol in the form doesn't match the stock being edited.")


def test_switching_to_watching_clears_shares_and_price_and_back(client):
    client.post("/api/holdings", json=HOLD)
    r = client.put("/api/holdings/ABB", json={"watching": True})
    assert r.json()["watching"] is True and r.json()["shares"] is None and r.json()["buy_price"] is None
    r = client.put("/api/holdings/ABB", json={"watching": False, "shares": 10, "buy_price": 100})
    assert r.json()["watching"] is False and r.json()["shares"] == 10


def test_update_validation_and_missing(client):
    client.post("/api/holdings", json=HOLD)
    err(client.put("/api/holdings/ABB", json={"shares": 0, "buy_price": 5}), 400, "bad_request",
        "Enter the number of shares as a whole number, 1 or more.")
    err(client.put("/api/holdings/TITAN", json={"shares": 1, "buy_price": 5}), 404, "not_found",
        "TITAN isn't in your stocks.")
    err(client.put("/api/holdings/BAD SYMBOL", json={"shares": 1, "buy_price": 5}), 400, "bad_request",
        "That doesn't look like an NSE symbol.")


# ------------------------------------------------------------------ delete
def test_delete_removes_the_row_but_keeps_reports(client):
    client.post("/api/holdings", json=HOLD)
    assert client.delete("/api/holdings/ABB").json() == {"deleted": True}
    err(client.delete("/api/holdings/ABB"), 404, "not_found", "ABB isn't in your stocks.")
    from backend.app import holdings
    assert holdings.get_holding("ABB") is None
