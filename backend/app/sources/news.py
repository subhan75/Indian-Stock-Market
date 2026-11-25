"""Google News RSS for a company: trusted outlets only, last 30 days, de-duplicated."""
import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Callable
from urllib.parse import quote

import feedparser
import requests

from .base import SourceUnavailable
from .prices import IST

MAX_HEADLINES = 20
WINDOW_DAYS = 30
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockAnalystV0/0.1; personal research tool)"}

# normalised outlet text -> name shown on screen. Must match config.TRUSTED_OUTLETS.
ALIASES = {
    "economictimes": "Economic Times", "etmarkets": "Economic Times",
    "businessstandard": "Business Standard",
    "mint": "Mint", "livemint": "Mint",
    "moneycontrol": "Moneycontrol",
    "hindubusinessline": "The Hindu BusinessLine", "businessline": "The Hindu BusinessLine",
    "financialexpress": "Financial Express",
    "cnbctv18": "CNBC-TV18",
    "reuters": "Reuters",
}


@dataclass
class Headline:
    title: str
    outlet: str          # canonical trusted-outlet name
    published: datetime  # timezone-aware
    url: str
    description: str = ""

    @property
    def date_display(self) -> str:
        d = self.published.astimezone(IST)
        return f"{d.day} {d:%b}"


@dataclass
class NewsResult:
    ok: bool
    headlines: list[Headline]
    fetched_at: datetime
    url: str = ""
    note: str = ""


def feed_url(company_name: str) -> str:
    return (f'https://news.google.com/rss/search?q={quote(chr(34) + company_name + chr(34))}'
            f'+when:{WINDOW_DAYS}d&hl=en-IN&gl=IN&ceid=IN:en')


def canonical_outlet(raw: str) -> str | None:
    """Map whatever Google calls the publisher ('The Economic Times', 'cnbctv18.com') to a trusted name."""
    key = re.sub(r"[^a-z0-9]", "", raw.lower())
    if key.startswith("the"):
        key = key[3:]
    for suffix in ("com", "in"):
        if key.endswith(suffix) and key[: -len(suffix)] in ALIASES:
            key = key[: -len(suffix)]
            break
    return ALIASES.get(key)


def _strip_outlet_suffix(title: str, outlet_raw: str) -> str:
    """Google appends ' - Outlet' to every title."""
    suffix = f" - {outlet_raw}"
    return title[: -len(suffix)].rstrip() if outlet_raw and title.endswith(suffix) else title


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


def is_duplicate(a: Headline, b: Headline) -> bool:
    if a.url == b.url:
        return True
    na, nb = _norm_title(a.title), _norm_title(b.title)
    return na == nb or SequenceMatcher(None, na, nb).ratio() >= 0.9


def parse_feed(content: bytes | str, now: datetime | None = None) -> list[Headline]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=WINDOW_DAYS)
    out: list[Headline] = []
    for entry in feedparser.parse(content).entries:
        outlet_raw = (entry.get("source") or {}).get("title", "")
        outlet = canonical_outlet(outlet_raw)
        parsed = entry.get("published_parsed")
        link = entry.get("link", "")
        if not outlet or not parsed or not link:
            continue
        published = datetime(*parsed[:6], tzinfo=timezone.utc)
        if published < cutoff or published > now + timedelta(hours=1):
            continue
        title = _strip_outlet_suffix(entry.get("title", "").strip(), outlet_raw)
        if title:
            out.append(Headline(title, outlet, published, link))
    out.sort(key=lambda h: h.published, reverse=True)
    unique: list[Headline] = []
    for h in out:
        if not any(is_duplicate(h, u) for u in unique):
            unique.append(h)
    return unique[:MAX_HEADLINES]


def _http_get(url: str) -> requests.Response:
    return requests.get(url, headers=HEADERS, timeout=20)


def fetch_news(company_name: str, http_get: Callable[[str], requests.Response] = _http_get,
               now: datetime | None = None) -> NewsResult:
    url = feed_url(company_name)
    fetched = datetime.now(timezone.utc)
    try:
        resp = http_get(url)
        if resp.status_code != 200:
            raise SourceUnavailable(f"Google News answered with an error ({resp.status_code}).")
        return NewsResult(True, parse_feed(resp.content, now), fetched, url)
    except (requests.RequestException, SourceUnavailable):
        return NewsResult(False, [], fetched, url, "Couldn't fetch news right now.")


# ----------------------------------------------------------------------------- plain outlet feeds (Phase 3)
DESCRIPTION_MAX_CHARS = 200
_TAGS = re.compile(r"<[^>]+>")


def clean_description(raw: str) -> str:
    """Feed descriptions often contain HTML. Show plain text only, capped in length."""
    text = " ".join(html.unescape(_TAGS.sub(" ", raw or "")).split())
    return text if len(text) <= DESCRIPTION_MAX_CHARS else text[: DESCRIPTION_MAX_CHARS - 1].rstrip() + "…"


def parse_plain_feed(content: bytes | str, outlet: str, now: datetime | None = None,
                     window_hours: int = 24) -> list[Headline]:
    """Headlines from an outlet's own RSS feed (no Google 'source' tag): the outlet is fixed by the caller.
    Items with no date, link or title are dropped, as are items outside the time window."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)
    out: list[Headline] = []
    for entry in feedparser.parse(content).entries:
        parsed, link, title = entry.get("published_parsed"), entry.get("link", ""), (entry.get("title") or "").strip()
        if not (parsed and link and title):
            continue
        published = datetime(*parsed[:6], tzinfo=timezone.utc)
        if published < cutoff or published > now + timedelta(hours=1):
            continue
        out.append(Headline(title, outlet, published, link, clean_description(entry.get("summary", ""))))
    out.sort(key=lambda h: h.published, reverse=True)
    return out


def merge_headlines(*feeds: list[Headline]) -> list[Headline]:
    """Several feeds into one list: newest first, the same story (link or near-identical title) only once."""
    merged = sorted((h for feed in feeds for h in feed), key=lambda h: h.published, reverse=True)
    unique: list[Headline] = []
    for h in merged:
        if not any(is_duplicate(h, u) for u in unique):
            unique.append(h)
    return unique
