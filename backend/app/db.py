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
