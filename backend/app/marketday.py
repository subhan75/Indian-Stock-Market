"""GET /api/market/today (Phase 3 spec, section 5).

The market part (indices, headlines, AI points) is cached for MARKET_CACHE_MINUTES so a reload doesn't repeat
the AI call. Your stocks and Watching are recomputed on every request. Nothing here raises: a failing source
greys out its own block only.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import ai, config, holdings, report
from .db import connect
from .matching import find_stock_news
from .sources import market as src
from .sources import news
from .sources.prices import IST, format_clock, format_time

log = logging.getLogger("stock_analyst.market")
CACHE_KEY = "market:today"


@dataclass
class MarketDeps:
    """Everything that touches the outside world, so tests can replace it."""
    index: Callable = src.fetch_index
    feed: Callable = src.fetch_feed
    llm: ai.LLM | None = field(default_factory=ai.get_llm)


# ----------------------------------------------------------------------------- cache
def _read_cache() -> tuple[dict, datetime] | None:
    with connect() as conn:
        row = conn.execute("SELECT body, fetched_at FROM page_cache WHERE url = ?", (CACHE_KEY,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["body"]), datetime.fromisoformat(row["fetched_at"])
    except (ValueError, TypeError):
        return None


def _write_cache(part: dict, when: datetime) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO page_cache (url, body, fetched_at) VALUES (?,?,?) "
            "ON CONFLICT(url) DO UPDATE SET body=excluded.body, fetched_at=excluded.fetched_at",
            (CACHE_KEY, json.dumps(part, ensure_ascii=False), when.isoformat()),
        )


def _fresh_cache(now: datetime) -> dict | None:
    cached = _read_cache()
    if cached and now - cached[1] < timedelta(minutes=config.MARKET_CACHE_MINUTES):
        return cached[0]
    return None


# ----------------------------------------------------------------------------- building the market part
def _safe_index(fn, name, ticker, url) -> src.IndexResult:
    try:
        return fn(name, ticker, url)
    except Exception:
        return src.IndexResult(name, url, False)


def _safe_feed(fn, name, url) -> src.FeedResult:
    try:
        return fn(name, url)
    except Exception:
        return src.FeedResult(name, False, [])


def _source_row(name: str, ok: bool, when: datetime, last_ok: dict[str, str]) -> dict:
    row = {"name": name, "ok": ok, "fetched_at_display": format_time(when)}
    if not ok and name in last_ok:
        row["last_ok_display"] = last_ok[name]
    return row


def build_part(deps: MarketDeps, now: datetime) -> tuple[dict, bool]:
    """Returns (market part, cacheable). Cacheable needs at least one index and one feed to have worked."""
    with ThreadPoolExecutor(max_workers=len(src.INDICES) + len(src.FEEDS)) as pool:
        index_futures = [pool.submit(_safe_index, deps.index, *spec) for spec in src.INDICES]
        feed_futures = [pool.submit(_safe_feed, deps.feed, *spec) for spec in src.FEEDS]
    indices = [f.result() for f in index_futures]
    feeds = [f.result() for f in feed_futures]

    pool_headlines = news.merge_headlines(*[f.headlines for f in feeds])
    shown = pool_headlines[: config.MARKET_HEADLINES_SHOWN]
    ok_indices = [i for i in indices if i.ok]

    points = ai.write_market_points(
        deps.llm,
        [{"name": i.name, "level": int(round(i.level)), "change_percent": i.change_pct} for i in ok_indices],
        [{"id": f"H{n}", "title": h.title, "outlet": h.outlet, "time": format_clock(h.published, now),
          "description": h.description} for n, h in enumerate(shown, start=1)],
    ) or []

    previous = _read_cache()
    last_ok = {s["name"]: s["fetched_at_display"] for s in previous[0].get("sources", []) if s.get("ok")} if previous else {}
    # every source was fetched within seconds of each other, so they share the page's own timestamp
    sources = [_source_row("Yahoo Finance", all(i.ok for i in indices), now, last_ok)]
    sources += [_source_row(f.name, f.ok, now, last_ok) for f in feeds]

    part = {
        "generated_at": now.isoformat(),
        "indices": [src.index_block(i) for i in ok_indices],
        "points": points,
        "pool": [{"title": h.title, "outlet": h.outlet, "published": h.published.isoformat(), "url": h.url}
                 for h in pool_headlines],
        "sources": sources,
    }
    return part, bool(ok_indices) and any(f.ok for f in feeds)


# ----------------------------------------------------------------------------- the response
def _pool_headlines(part: dict) -> list[news.Headline]:
    return [news.Headline(h["title"], h["outlet"], datetime.fromisoformat(h["published"]), h["url"])
            for h in part["pool"]]


def assemble(part: dict, now: datetime) -> dict:
    pool = _pool_headlines(part)
    shown = pool[: config.MARKET_HEADLINES_SHOWN]
    shown_ids = {h.url: f"H{n}" for n, h in enumerate(shown, start=1)}
    by_url = {h.url: h for h in pool}

    stocks = holdings.list_holdings()
    stock_news = find_stock_news([{"symbol": s["symbol"], "name": s["name"]} for s in stocks], pool, shown_ids)
    for row in stock_news:
        row["time_display"] = format_clock(by_url[row["url"]].published, now)

    watching = []
    for s in sorted((s for s in stocks if s["watching"]), key=lambda s: s["name"].lower()):
        latest = report.latest_report(s["symbol"])
        watching.append({"symbol": s["symbol"], "name": s["name"], "label": latest["label"] if latest else None,
                         "report_url": f"/report.html?symbol={s['symbol']}"})

    return {
        "as_of": format_time(datetime.fromisoformat(part["generated_at"])),
        "indices": part["indices"],
        "points": part["points"],
        "headlines": [{"id": shown_ids[h.url], "title": h.title, "outlet": h.outlet,
                       "time_display": format_clock(h.published, now), "url": h.url} for h in shown],
        "your_stocks_in_news": stock_news,
        "watching": watching,
        "sources": part["sources"],
        "ai_text": bool(part["points"]),
        "disclaimer": config.DISCLAIMER,
    }


def get_market(refresh: bool = False, deps: MarketDeps | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    part = None if refresh else _fresh_cache(now)
    if part is None:
        try:
            part, cacheable = build_part(deps or MarketDeps(), now)
        except Exception:
            log.exception("Building the market page failed")
            part, cacheable = {"generated_at": now.isoformat(), "indices": [], "points": [], "pool": [],
                               "sources": [_source_row(n, False, now, {})
                                           for n in ("Yahoo Finance", *[f[0] for f in src.FEEDS])]}, False
        if cacheable:
            _write_cache(part, now)
    return assemble(part, now)
