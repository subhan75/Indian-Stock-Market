"""Which of your stocks are in the news (Phase 3 spec, section 5.4). Plain code, no AI.

Matches headline *titles* only, by company-name phrase or by the all-caps ticker. Aliases such as
"SBI" or "HUL" are deliberately not matched in v0 (spec decision D7).
"""
import re
from dataclasses import dataclass

from . import config
from .sources.news import Headline

LEGAL_WORDS = {"limited", "ltd", "ltd.", "corporation", "corp", "company", "co", "co.", "inc"}
MIN_STEM_CHARS = 4
MIN_TICKER_LETTERS = 3


def name_stem(name: str) -> str:
    """'ABB India Limited' -> 'abb india'; 'Titan Company Limited' -> 'titan'."""
    text = re.sub(r"\([^)]*\)", " ", name.lower())
    words = text.split()
    while words and words[-1] in LEGAL_WORDS:
        words.pop()
    return " ".join(words)


def _boundary(core: str) -> str:
    return r"(?<![A-Za-z0-9])" + core + r"(?![A-Za-z0-9])"


@dataclass
class Matcher:
    symbol: str
    name: str
    stem: re.Pattern | None      # case-insensitive company-name phrase
    ticker: re.Pattern | None    # case-sensitive all-caps symbol

    def matches(self, title: str) -> bool:
        return bool((self.stem and self.stem.search(title)) or (self.ticker and self.ticker.search(title)))


def build_matcher(symbol: str, name: str) -> Matcher:
    stem_text = name_stem(name)
    stem = None
    if len(stem_text) >= MIN_STEM_CHARS:
        phrase = r"\s+".join(re.escape(word) for word in stem_text.split())
        stem = re.compile(_boundary(phrase), re.IGNORECASE)
    ticker = None
    if symbol.isalpha() and len(symbol) >= MIN_TICKER_LETTERS:
        ticker = re.compile(_boundary(re.escape(symbol.upper())))    # no IGNORECASE: "IDEA" is not "idea"
    return Matcher(symbol, name, stem, ticker)


def find_stock_news(stocks: list[dict], pool: list[Headline], shown_ids: dict[str, str]) -> list[dict]:
    """stocks: [{symbol, name}]; pool: all recent headlines, newest first;
    shown_ids: headline url -> 'H#' for the headlines on the page.

    One row per (stock, headline), newest first, at most MATCH_MAX_PER_STOCK per stock and MATCH_MAX_TOTAL
    overall. `headline_id` is None when the headline is not among the ones shown.
    """
    rows: list[tuple[Headline, dict]] = []
    for stock in stocks:
        matcher = build_matcher(stock["symbol"], stock["name"])
        hits = [h for h in pool if matcher.matches(h.title)][: config.MATCH_MAX_PER_STOCK]
        for h in hits:
            rows.append((h, {"symbol": stock["symbol"], "name": stock["name"],
                             "headline_id": shown_ids.get(h.url), "title": h.title, "outlet": h.outlet,
                             "url": h.url, "report_url": f"/report.html?symbol={stock['symbol']}"}))
    rows.sort(key=lambda pair: pair[0].published, reverse=True)
    return [row for _, row in rows[: config.MATCH_MAX_TOTAL]]
