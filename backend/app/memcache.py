"""A tiny thread-safe, size-capped in-memory cache for public data (Screener pages, the market page).

Public data is cached in the backend's memory rather than in the database: without a secret key the backend
cannot safely write shared tables, and these caches are cheap to rebuild after a restart.
"""
import threading
from collections import OrderedDict
from typing import Any


class MemCache:
    def __init__(self, max_entries: int = 300):
        self._max = max_entries
        self._data: "OrderedDict[str, Any]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key not in self._data:
                return default
            self._data.move_to_end(key)
            return self._data[key]

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)   # evict the least recently used

    def pop(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


# One cache per kind of data, shared by every user (it is all public).
pages = MemCache(max_entries=300)    # Screener pages, ~200 KB each
market = MemCache(max_entries=4)     # the Market today page
verified = MemCache(max_entries=1000)    # access tokens Supabase vouched for, for a few seconds (see auth.py)
refreshed = MemCache(max_entries=1000)   # sessions just renewed, so simultaneous requests don't burn a refresh token


def clear_all() -> None:
    """Used by tests to start from nothing."""
    pages.clear()
    market.clear()
    verified.clear()
    refreshed.clear()
