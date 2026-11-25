"""The "Look at this" flag (Phase 2 spec, section 4.4). Pure code: no network, no AI.

The flag says *why* a stock deserves a look. It never says what to do, and every text here is a
fixed sentence so it cannot contain advice wording.
"""
import math

from . import config

RANK = {"looks_solid": 3, "mixed": 2, "be_careful": 1}
ORDER = ["be_careful", "label_worse", "price_drop", "serious_news"]


def _reason(code: str, text: str) -> dict:
    return {"code": code, "text": text}


def _grey_ids(report: dict) -> set[str]:
    return {q["id"] for q in report.get("questions", []) if q.get("status") == "grey"}


def _news_ok(report: dict) -> bool:
    return any(s.get("name") == "Google News" and s.get("ok") for s in report.get("sources", []))


def _label_worse(latest: dict, previous: dict | None) -> dict | None:
    if previous is None:
        return None
    new, old = latest.get("label", {}), previous.get("label", {})
    if RANK.get(new.get("code"), 0) == 0 or RANK.get(old.get("code"), 0) == 0:
        return None
    if RANK[new["code"]] >= RANK[old["code"]]:
        return None
    if _grey_ids(latest) - _grey_ids(previous):
        return None  # a data outage, not a real change: greys can lower a label by themselves
    return _reason("label_worse", f"Label went from {old['display']} to {new['display']}")


def _serious_news(latest: dict, previous: dict | None) -> dict | None:
    if previous is None or not _news_ok(previous):
        return None
    seen = {n.get("url") for n in previous.get("news", [])}
    if any(n.get("serious") is True and n.get("url") not in seen for n in latest.get("news", [])):
        return _reason("serious_news", "New serious news since the last refresh")
    return None


def _price_drop(buy_price: float | None, price: float | None) -> dict | None:
    if not buy_price or buy_price <= 0 or price is None:
        return None
    drop = round((buy_price - price) / buy_price * 100, 2)
    if drop < config.FLAG_PRICE_DROP_PCT:
        return None
    return _reason("price_drop", f"Price is {math.floor(drop)}% below what you paid")


def evaluate(*, watching: bool, buy_price: float | None, price: float | None,
             latest: dict | None, previous: dict | None) -> list[dict]:
    """Reasons this stock is flagged, in a fixed order. Empty means no flag.

    latest / previous are the two newest stored reports (previous may be None). With no report at all
    there is no flag, whatever the price.
    """
    if latest is None:
        return []
    found: dict[str, dict | None] = {
        "be_careful": _reason("be_careful", "Label is Be careful")
        if latest.get("label", {}).get("code") == "be_careful" else None,
        "label_worse": _label_worse(latest, previous),
        "price_drop": None if watching else _price_drop(buy_price, price),
        "serious_news": _serious_news(latest, previous),
    }
    return [found[code] for code in ORDER if found[code]]


def flag_block(reasons: list[dict]) -> dict:
    return {"on": bool(reasons), "reasons": reasons, "reason": "; ".join(r["text"] for r in reasons)}


def report_price(report: dict | None) -> float | None:
    """The price recorded in a report (used for report-derived codes, spec decision D5)."""
    value = (report or {}).get("price", {}).get("value")
    return float(value) if isinstance(value, (int, float)) else None


def report_codes(*, watching: bool, buy_price: float | None, latest: dict | None, previous: dict | None) -> set[str]:
    """Flag codes derived only from stored reports, used to decide which flags are *new* after a refresh."""
    return {r["code"] for r in evaluate(watching=watching, buy_price=buy_price, price=report_price(latest),
                                        latest=latest, previous=previous)}
