import json

from fastapi.testclient import TestClient

from backend.app.db import connect
from backend.app.main import app
from backend.app.sources import nse

CSV = """SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
ABB,ABB India Limited,EQ,02-JAN-1996,2,1,INE117A01022,2
POLYCAB,Polycab India Limited,EQ,16-APR-2019,10,1,INE455K01017,10
BAJFINANCE,Bajaj Finance Limited,EQ,05-JUN-2003,2,1,INE296A01024,2
INFY,Infosys Limited,EQ,08-FEB-1995,5,1,INE009A01021,5
SMEONLY,Some SME Ltd,SM,01-JAN-2020,10,1,INE000000001,10
ABBOTINDIA,Abbott India Limited,EQ,01-JAN-2000,10,1,INE358A01014,10
"""


def seed():
    nse.store_companies(nse.parse_equity_csv(CSV))


def test_parse_keeps_only_eq_and_be():
    symbols = {r["symbol"] for r in nse.parse_equity_csv(CSV)}
    assert "SMEONLY" not in symbols
    assert {"ABB", "POLYCAB", "BAJFINANCE", "INFY", "ABBOTINDIA"} <= symbols


def test_search_ranks_exact_symbol_then_prefix_then_name():
    seed()
    result = nse.search("abb")
    assert [r["symbol"] for r in result][:2] == ["ABB", "ABBOTINDIA"]
    assert nse.search("bajaj")[0]["symbol"] == "BAJFINANCE"
    assert nse.search("") == []


def test_stale_when_empty_then_fresh_after_store():
    assert nse.is_stale()
    seed()
    assert not nse.is_stale()


def test_search_endpoint(monkeypatch):
    seed()
    monkeypatch.setattr(nse, "refresh_companies", lambda force=False: 0)
    with TestClient(app) as client:
        r = client.get("/api/stocks/search", params={"q": "infosys"})
        assert r.status_code == 200
        assert r.json() == [{"symbol": "INFY", "name": "Infosys Limited"}]
        assert client.get("/api/stocks/search", params={"q": "x" * 200}).status_code == 400


def test_search_endpoint_reports_source_unavailable(monkeypatch):
    def boom(force=False):
        raise nse.SourceUnavailable("Couldn't fetch the NSE company list: down")

    monkeypatch.setattr(nse, "refresh_companies", boom)
    with TestClient(app) as client:
        r = client.get("/api/stocks/search", params={"q": "abb"})
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "source_unavailable"


def test_recent_reports_newest_first_one_per_stock(monkeypatch):
    seed()
    rows = [
        ("ABB", "2026-11-20T10:00:00+05:30", "mixed"),
        ("ABB", "2026-11-25T10:00:00+05:30", "looks_solid"),
        ("INFY", "2026-11-22T10:00:00+05:30", "be_careful"),
    ]
    with connect() as conn:
        conn.executemany(
            "INSERT INTO reports (symbol, generated_at, label, report_json) VALUES (?,?,?,?)",
            [(s, g, l, json.dumps({})) for s, g, l in rows],
        )
    with TestClient(app) as client:
        data = client.get("/api/reports/recent").json()
    assert [d["symbol"] for d in data] == ["ABB", "INFY"]
    assert data[0]["label"] == "looks_solid"
    assert data[0]["name"] == "ABB India Limited"
