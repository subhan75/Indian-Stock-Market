import pytest
import requests

from backend.app import auth, memcache, ratelimit, session, store
from backend.app.main import app
from backend.app.sources import nse

TEST_USER = auth.Identity("00000000-0000-0000-0000-0000000000aa", "tester@example.com", "test-access-token")


async def _signed_in_test_user():
    """Stands in for the real sign-in guard: every request is the test user (the store is the shared test store)."""
    return TEST_USER


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
    ratelimit.by_email.clear()
    ratelimit.by_address.clear()
    app.dependency_overrides[session.require_user] = _signed_in_test_user

    def no_network(self, method, url, *args, **kwargs):
        raise requests.ConnectionError(f"network is blocked in tests: {method} {url}")

    monkeypatch.setattr(requests.sessions.Session, "request", no_network)
    yield user_store
    app.dependency_overrides.pop(session.require_user, None)
    store.install_test_store(None)
    memcache.clear_all()
    nse.reset()


@pytest.fixture
def real_sign_in():
    """Use the REAL sign-in guard (the default test override is removed) for tests of login itself."""
    app.dependency_overrides.pop(session.require_user, None)
    yield
