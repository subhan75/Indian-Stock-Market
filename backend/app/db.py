import sqlite3
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    symbol TEXT PRIMARY KEY, name TEXT NOT NULL, series TEXT, isin TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS page_cache (
    url TEXT PRIMARY KEY, body TEXT NOT NULL, fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    symbol TEXT NOT NULL, generated_at TEXT NOT NULL, label TEXT, report_json TEXT NOT NULL,
    PRIMARY KEY (symbol, generated_at)
);
CREATE TABLE IF NOT EXISTS holdings (
    symbol    TEXT PRIMARY KEY,
    shares    INTEGER,
    buy_price REAL,
    watching  INTEGER NOT NULL DEFAULT 0 CHECK (watching IN (0, 1)),
    added_at  TEXT NOT NULL,
    CHECK (watching = 1 OR (shares IS NOT NULL AND buy_price IS NOT NULL AND shares > 0 AND buy_price > 0))
);
CREATE TABLE IF NOT EXISTS flags_sent (
    symbol  TEXT NOT NULL,
    reason  TEXT NOT NULL,
    sent_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_flags_sent ON flags_sent (symbol, sent_at);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
