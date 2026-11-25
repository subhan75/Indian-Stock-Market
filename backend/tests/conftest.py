import pytest
import requests

from backend.app import memcache, store
from backend.app.sources import nse


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """Every test starts with an empty signed-in user's store, empty memory caches and an empty company list.

    The store is installed process-wide because the test client runs the app in another thread. Real network
    calls through `requests` are blocked: tests must inject fakes (a leak would otherwise be slow and flaky).
    """
    user_store = store.InMemoryStore()
    store.install_test_store(user_store)
    memcache.clear_all()
    nse.reset()

    def no_network(self, method, url, *args, **kwargs):
        raise requests.ConnectionError(f"network is blocked in tests: {method} {url}")

    monkeypatch.setattr(requests.sessions.Session, "request", no_network)
    yield user_store
    store.install_test_store(None)
    memcache.clear_all()
    nse.reset()
