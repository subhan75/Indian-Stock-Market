"""Run the real app locally against an in-memory FAKE Supabase (sign-in and saved data), for trying the screens
and for browser tests without a Supabase project. Nothing here touches a real database or a real login.

    set ALLOW_FAKE_SUPABASE=1        (PowerShell: $env:ALLOW_FAKE_SUPABASE = "1")
    python scripts/dev_fake_server.py [port]

Sign in with the fake account printed at start-up. Everything saved lives only until you stop the server. The data
sources (Screener, news, prices, OpenAI) are the real ones, so reports still take real time.
"""
import os
import sys
from pathlib import Path

if os.environ.get("ALLOW_FAKE_SUPABASE") != "1":
    sys.exit("Refusing to start: this server uses a FAKE login and is for local development only.\n"
             "Set ALLOW_FAKE_SUPABASE=1 to confirm that is what you want.")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend" / "tests"))

import uvicorn  # noqa: E402

from backend.app import config, store_supabase  # noqa: E402
from backend.app.main import app  # noqa: E402
from fake_supabase import FakeSupabase  # noqa: E402

EMAILS = {"dev@example.com": "dev-password-123", "partner@example.com": "partner-password-123"}

fake = FakeSupabase()
for email, password in EMAILS.items():
    fake.auth.add_user(email, password)

config.SUPABASE_URL = "https://fake.supabase.co"
config.SUPABASE_PUBLISHABLE_KEY = "sb_publishable_FAKE"
config.COOKIE_SECURE = False                     # plain http on localhost
config.ALLOWED_ORIGINS = []
store_supabase._shared_http = fake.http_client()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print("FAKE Supabase in use. Fake accounts:")
    for email, password in EMAILS.items():
        print(f"  {email} / {password}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
