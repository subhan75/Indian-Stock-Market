"""Central settings. Cut-offs live here so they are easy to tune after reading real reports."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

FRONTEND_DIR = ROOT / "frontend"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
LABELLER_MODEL = os.getenv("LABELLER_MODEL", "")
WRITER_MODEL = os.getenv("WRITER_MODEL", "")

# Supabase: the project URL and the PUBLISHABLE (anon) key only. This project never uses a secret / service-role
# key, so nothing can bypass Row Level Security. Set these as environment variables (Railway, your shell).
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
DB_TIMEOUT_SECONDS = 10
DB_RETRY_READS = True        # supabase-py retries failed reads (not writes) a couple of times with a short delay

# Login cookies and CSRF (origins allowed to send POST/PUT/DELETE; the local server's own origin is always allowed)
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").strip().lower() not in {"0", "false", "no"}
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

CACHE_TTL_HOURS = 24
SCREENER_MIN_GAP_SECONDS = 3   # be polite: wait between Screener requests
COMPANY_LIST_TTL_DAYS = 7

# Question cut-offs (v0 doc, "The five questions")
GROWTH_GREEN_MIN = 10.0      # % sales growth, last 4 quarters vs previous 4
GROWTH_AMBER_MIN = 0.0
ROCE_GREEN_MIN = 15.0
ROCE_AMBER_MIN = 10.0
DEBT_GREEN_MAX = 0.5
DEBT_AMBER_MAX = 1.0
PE_GREEN_MAX_RATIO = 1.0
PE_AMBER_MAX_RATIO = 1.5
MIN_PEERS = 3                # to confirm while building

# Phase 2 (My stocks)
FLAG_PRICE_DROP_PCT = 20
MAX_HOLDINGS = 100
MAX_SHARES = 10_000_000
MAX_BUY_PRICE = 10_000_000

# Phase 3 (Market today)
MARKET_CACHE_MINUTES = 15
MARKET_WINDOW_HOURS = 24
MARKET_HEADLINES_SHOWN = 10
MARKET_POINTS_MAX = 3
MATCH_MAX_PER_STOCK = 3
MATCH_MAX_TOTAL = 10

TRUSTED_OUTLETS = [
    "Economic Times", "Business Standard", "Mint", "Moneycontrol",
    "The Hindu BusinessLine", "Financial Express", "CNBC-TV18", "Reuters",
]

BANNED_WORDS = ["buy", "sell", "target", "recommend"]
DISCLAIMER = "Research aid, not financial advice."
