"""Builds the Report JSON from the v0 contract: fetch -> score -> AI text -> save.

A failing source never stops the report: its question goes grey and the footer says so.
All strings arrive display-ready, so the frontend does no maths.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import ai, config, scoring
from .db import connect
from .errors import ApiError
from .scoring import QuestionResult
from .sources import news as news_src
from .sources import nse, prices, screener
from .sources.base import NotFound, SourceUnavailable
from .sources.prices import IST, format_time

FETCH_FAILED = "Couldn't fetch this right now."
SCREENER_QUESTIONS = ("growth", "efficiency", "debt", "price")
ABOUT_FACT_MAX_CHARS = 700


@dataclass
class Deps:
    """Everything that touches the outside world, so tests can swap it out."""
    screener: Callable = screener.fetch_company
    price: Callable = prices.fetch_price
    news: Callable = news_src.fetch_news
    llm: ai.LLM | None = field(default_factory=ai.get_llm)


# ----------------------------------------------------------------------------- cache
def latest_report(symbol: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT report_json FROM reports WHERE symbol = ? COLLATE NOCASE ORDER BY generated_at DESC LIMIT 1",
            (symbol,),
        ).fetchone()
    return json.loads(row["report_json"]) if row else None


def _fresh(report: dict) -> bool:
    try:
        age = datetime.now(IST) - datetime.fromisoformat(report["generated_at"])
    except (KeyError, ValueError):
        return False
    return age < timedelta(hours=config.CACHE_TTL_HOURS)


def _save(report: dict) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO reports (symbol, generated_at, label, report_json) VALUES (?,?,?,?)",
            (report["symbol"], report["generated_at"], report["label"]["code"],
             json.dumps(report, ensure_ascii=False)),
        )


def get_report(symbol: str, refresh: bool = False, deps: Deps | None = None) -> dict:
    symbol = symbol.strip().upper()
    if not refresh:
        cached = latest_report(symbol)
        if cached and _fresh(cached):
            return cached
    report = build_report(symbol, deps or Deps())
    _save(report)
    return report


# ----------------------------------------------------------------------------- helpers
def _company(symbol: str) -> dict:
    company = nse.get_company(symbol)
    if company is None:
        try:
            nse.refresh_companies()
        except SourceUnavailable as exc:
            raise ApiError("source_unavailable", str(exc))
        company = nse.get_company(symbol)
    if company is None:
        raise ApiError("not_found", f"{symbol} isn't on the NSE equity list. Check the symbol or search by company name.")
    return company


def _last_ok_times(symbol: str) -> dict[str, str]:
    """When each source last worked, taken from the most recent stored report."""
    previous = latest_report(symbol)
    return {s["name"]: s["fetched_at_display"] for s in (previous or {}).get("sources", []) if s.get("ok")}


def _safe(summary: str, title: str) -> str:
    """Summaries are shown as our words, so they follow the same no-advice rule."""
    return title if not summary or ai.has_banned_word(summary) else summary


# ----------------------------------------------------------------------------- build
def build_report(symbol: str, deps: Deps) -> dict:
    company = _company(symbol)
    name = company["name"]
    generated = datetime.now(IST)

    # 1. Fetch the three independent sources in parallel.
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_screener = pool.submit(deps.screener, symbol)
        f_news = pool.submit(deps.news, name)
    screener_error = None
    try:
        data = f_screener.result()
    except NotFound:
        data, screener_error = None, "Screener.in has no page for this stock."
    except SourceUnavailable as exc:
        data, screener_error = None, str(exc)
    except Exception:  # a page we can't read must degrade the report, not break it
        data, screener_error = None, "Couldn't read Screener.in's page."
    if data is None:
        data = screener.ScreenerData(symbol=symbol, url=f"{screener.BASE}/company/{symbol}/",
                                     fetched_at=generated.isoformat(), consolidated=False)
    price_result = deps.price(symbol, data.price, data.url)  # needs Screener's price as the fallback
    try:
        news_result = f_news.result()
    except Exception:
        news_result = news_src.NewsResult(False, [], generated, note=FETCH_FAILED)

    # 2. Label the headlines (AI), then score everything (code).
    headlines = [{"id": f"N{i}", "title": h.title, "outlet": h.outlet, "date": h.date_display}
                 for i, h in enumerate(news_result.headlines, start=1)]
    by_id = {f"N{i}": h for i, h in enumerate(news_result.headlines, start=1)}
    labels = ai.label_headlines(deps.llm, name, headlines) if news_result.ok else None
    news_labels = None if labels is None else [x.as_news_label() for x in labels.values()]
    results, label = scoring.score_all(data, news_labels)

    if screener_error:
        for r in results:
            if r.id in SCREENER_QUESTIONS:
                r.value_display = FETCH_FAILED
    if not news_result.ok:
        results[-1].value_display = FETCH_FAILED
    elif not headlines:
        # Green by the v0 rule, but say plainly that no trusted headlines were found at all.
        results[-1].value_display = "No headlines from trusted outlets in the last 30 days."
    elif labels is None:
        results[-1].value_display = "Couldn't check the headlines right now."

    # 3. Which headlines to show.
    if labels is not None:
        shown = ai.pick_top_news(headlines, labels, n=3)
    else:
        shown = headlines[:3]
    news_items = []
    for h in shown:
        lab = labels.get(h["id"]) if labels else None
        original = by_id[h["id"]]
        news_items.append({
            "id": h["id"], "title": h["title"], "outlet": h["outlet"], "date_display": h["date"],
            "summary": _safe(lab.summary, h["title"]) if lab else "",
            "tone": lab.tone if lab else "neutral", "url": original.url,
        })

    # 4. Number the facts and wire each question to its facts.
    facts: list[dict] = []
    questions: list[dict] = []
    for r in results:
        cites = []
        for fd in r.facts:
            fid = f"F{len(facts) + 1}"
            facts.append({"id": fid, "label": fd.label, "value_display": fd.value_display,
                          "source": fd.source, "url": fd.url, "as_of": fd.as_of})
            cites.append(fid)
        if r.id == "news":
            cites = [n["id"] for n in news_items if n["tone"] == "bad"] or []
        questions.append({"id": r.id, "question": r.question, "status": r.status,
                          "value_display": r.value_display, "meaning": r.meaning, "cites": cites})
    if data.about:
        facts.append({"id": f"F{len(facts) + 1}", "label": "What the company does (company description)",
                      "value_display": data.about[:ABOUT_FACT_MAX_CHARS], "source": "Screener.in",
                      "url": data.url, "as_of": "Latest"})

    # 5. AI-written text, only if the facts include a description to write "about" from.
    text = None
    if data.about:
        text = ai.write_report_text(
            deps.llm, name,
            [{"id": f["id"], "label": f["label"], "value": f["value_display"], "as_of": f["as_of"]} for f in facts],
            [{"id": n["id"], "title": n["title"], "date": n["date_display"], "summary": n["summary"]} for n in news_items],
            [{"question": q["question"], "status": q["status"], "value": q["value_display"]} for q in questions],
            label["display"],
        )
    empty = {"text": "", "cites": []}

    # 6. Sources footer.
    last_ok = _last_ok_times(symbol)

    def source(name_: str, ok: bool, when: datetime | None) -> dict:
        entry = {"name": name_, "ok": ok,
                 "fetched_at_display": format_time(when) if when else ""}
        if not ok and name_ in last_ok:
            entry["last_ok_display"] = last_ok[name_]
        return entry

    try:
        screener_time = datetime.fromisoformat(data.fetched_at)
    except ValueError:
        screener_time = generated
    sources = [
        source("Screener.in", screener_error is None, screener_time),
        source(price_result.source or "Yahoo Finance", price_result.ok, price_result.fetched_at),
        source("Google News", news_result.ok, news_result.fetched_at),
    ]
    if price_result.source == "Screener.in":
        sources[1] = source("Yahoo Finance", False, price_result.fetched_at)  # we fell back; say so

    return {
        "symbol": symbol,
        "name": name,
        "generated_at": generated.isoformat(timespec="seconds"),
        "price": prices.price_block(price_result),
        "label": label,
        "overall": text["overall"] if text else empty,
        "about": text["about"] if text else empty,
        "questions": questions,
        "news": news_items,
        "facts": facts,
        "sources": sources,
        "ai_text": text is not None,
        "disclaimer": config.DISCLAIMER,
    }
