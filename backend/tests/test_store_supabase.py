import re
import subprocess
from pathlib import Path

import httpx
import pytest

from backend.app import config, store_supabase
from backend.app.store import Conflict, StoreError
from backend.app.store_supabase import NotAuthorized, SupabaseStore, make_client
from fake_postgrest import FakePostgrest, error

ROOT = Path(__file__).resolve().parents[2]
USER = "00000000-0000-0000-0000-00000000000a"


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_PUBLISHABLE_KEY", "sb_publishable_TEST")
    return FakePostgrest()


def store_for(server):
    return SupabaseStore(make_client(server.token_for(USER), http=server.http_client()), USER)


# ------------------------------------------------------------------ requests carry the user's token, never anything stronger
def test_every_request_acts_as_the_signed_in_user_with_the_publishable_key(server):
    s = store_for(server)
    s.holdings_list()
    s.reports_recent("ABB", 1)
    token = server.token_for(USER)
    assert server.requests
    for request in server.requests:
        assert request.headers["authorization"] == f"Bearer {token}"
        assert request.headers["apikey"] == "sb_publishable_TEST"
        assert request.url.host == "fake.supabase.co"


def test_a_client_without_a_token_is_anonymous(server):
    make_client(None, http=server.http_client()).table("holdings").select("*")
    request_headers = []
    try:
        make_client(None, http=server.http_client()).table("holdings").select("*").execute()
    except Exception:
        pass
    request_headers = [r.headers["authorization"] for r in server.requests]
    assert request_headers == ["Bearer sb_publishable_TEST"]          # only the public key, no user identity


def test_each_request_gets_its_own_stateless_client(server):
    a = make_client("TOKEN-A", http=server.http_client())
    b = make_client("TOKEN-B", http=server.http_client())
    assert a is not b and a.options.headers["Authorization"] != b.options.headers["Authorization"]
    assert a.options.persist_session is False and a.options.auto_refresh_token is False


def test_the_shared_connection_pool_is_reused_between_clients():
    assert store_supabase.shared_http() is store_supabase.shared_http()


def test_an_unconfigured_project_fails_with_a_clear_message(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", "")
    assert store_supabase.configured() is False
    with pytest.raises(StoreError, match="isn't configured"):
        make_client("token")


# ------------------------------------------------------------------ errors become our own errors
def test_a_duplicate_is_a_conflict(server):
    s = store_for(server)
    row = {"symbol": "ABB", "shares": 1, "buy_price": 1.0, "watching": False, "added_at": "x"}
    s.holdings_insert(row)
    with pytest.raises(Conflict):
        s.holdings_insert(row)


@pytest.mark.parametrize("response", [
    error(401, "PGRST301", "JWT expired"),
    error(401, "PGRST303", "JWT issued at future"),
    error(400, "XX000", "Invalid JWT: signature mismatch"),
])
def test_a_rejected_token_means_not_authorized(server, response):
    server.fail_with = response
    with pytest.raises(NotAuthorized):
        store_for(server).holdings_list()


def test_a_missing_grant_names_the_fix_without_leaking_details(server):
    server.fail_with = error(403, "42501", "permission denied for table holdings")
    with pytest.raises(StoreError, match="supabase/schema.sql"):
        store_for(server).holdings_list()


@pytest.mark.parametrize("failure", [
    httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), httpx.ConnectTimeout("slow"), OSError("network down")])
def test_an_unreachable_database_is_a_store_error(server, failure, monkeypatch):
    monkeypatch.setattr(config, "DB_RETRY_READS", False)    # fail at once instead of waiting through retries
    server.fail_always = failure
    with pytest.raises(StoreError, match="isn't reachable"):
        store_for(server).holdings_list()


def test_an_unexpected_database_error_is_reported_without_internal_details(server):
    server.fail_with = error(500, "XX000", "internal secret detail about the server")
    with pytest.raises(StoreError) as caught:
        store_for(server).reports_recent("ABB", 1)
    assert "internal secret detail" not in str(caught.value) and "XX000" in str(caught.value)


def test_not_authorized_is_a_kind_of_store_error():
    assert issubclass(NotAuthorized, StoreError) and not issubclass(Conflict, StoreError)


# ------------------------------------------------------------------ exit criterion 1.3: no secret / service-role key anywhere
SECRET_PATTERNS = [
    (re.compile(r"sb_secret_[A-Za-z0-9_\-]{8,}"), "a Supabase secret key"),
    (re.compile(r"SUPABASE_(SECRET|SERVICE_ROLE)[A-Z_]*\s*[=:]"), "a secret-key setting"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "a JWT (could be a service_role key)"),
]


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    return [ROOT / f for f in out if f and not f.endswith((".png", ".jpg", ".ico", ".csv", ".html", ".xml"))
            or f.endswith((".py", ".md", ".sql", ".example", ".txt", ".json", ".toml", ".js", ".css"))]


def test_no_secret_or_service_role_key_exists_in_the_repository():
    this_file = Path(__file__).resolve()
    offenders = []
    for path in tracked_files():
        if not path.exists() or path.resolve() == this_file or path.name == "fake_postgrest.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern, label in SECRET_PATTERNS:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(ROOT)}: {label}")
    assert offenders == [], offenders


def test_the_loaded_settings_contain_no_secret_key_setting():
    names = {n.lower() for n in dir(config)}
    assert not [n for n in names if "secret" in n or "service_role" in n or "serviceRole".lower() in n]
    assert hasattr(config, "SUPABASE_PUBLISHABLE_KEY")


def test_the_schema_grants_nothing_to_anon_and_enables_row_level_security_everywhere():
    sql = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
    code = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    for table in ("holdings", "reports"):
        assert re.search(rf"alter table public\.{table}\s+enable row level security", code, re.I)
    assert not re.search(r"grant\s+[^;]*\bto\b[^;]*\banon\b", code, re.I)
    assert not re.search(r"grant\s+[^;]*\bto\b[^;]*service_role", code, re.I)
    assert "security definer" not in code.lower() and "user_metadata" not in code
    assert code.lower().count("create policy") == 8
    assert re.search(r"revoke all on public\.holdings\s+from anon, authenticated", code, re.I)


def test_a_one_off_network_blip_on_a_read_is_retried_by_the_client(server):
    """supabase-py retries transient GET failures itself, so a single blip never reaches the user."""
    server.fail_with = httpx.ConnectError("blip")
    assert store_for(server).holdings_list() == []


def test_writes_are_never_retried_so_a_failure_is_not_applied_twice(server):
    server.fail_always = httpx.ConnectError("down")
    with pytest.raises(StoreError):
        store_for(server).holdings_insert({"symbol": "ABB", "shares": 1, "buy_price": 1.0, "watching": False,
                                           "added_at": "x"})
    assert len([r for r in server.requests if r.method == "POST"]) == 1
