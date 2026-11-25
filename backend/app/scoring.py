"""The five questions and the overall label. Pure code, no network, no AI.

Every threshold comes from config so it can be tuned after reading real reports.
Each question is classified on the same rounded number it displays, so a value shown
as "10.0%" is never amber.
"""
from dataclasses import dataclass, field

from . import config
from .format import crore, pct
from .sources.screener import ScreenerData

SOURCE = "Screener.in"

QUESTION_TEXT = {
    "growth": "Is the business growing?",
    "efficiency": "Does it make money efficiently?",
    "debt": "Can it handle its debt?",
    "price": "Is the share price expensive?",
    "news": "Is anything bad happening?",
}
MEANING = {
    "growth": "A company that sells more each year usually has something people want.",
    "efficiency": "A good business turns the money put into it into profit; 15 rupees a year on every 100 invested is healthy.",
    "debt": "Too much borrowing makes a company fragile when times are bad.",
    "price": "Even a great company can be a poor buy if the price already assumes everything goes right.",
    "news": "Numbers only change every quarter; news tells you what's happening now.",
}
QUESTION_ORDER = ["growth", "efficiency", "debt", "price", "news"]

LENDER_WORDS = ("bank", "nbfc", "non banking", "housing finance", "microfinance", "financial institution")


@dataclass
class FactDraft:
    label: str
    value_display: str
    source: str
    url: str
    as_of: str


@dataclass
class QuestionResult:
    id: str
    status: str  # green | amber | red | grey
    value_display: str
    facts: list[FactDraft] = field(default_factory=list)

    @property
    def question(self) -> str:
        return QUESTION_TEXT[self.id]

    @property
    def meaning(self) -> str:
        return MEANING[self.id]


def _grey(qid: str, why: str = "Not enough data to answer this.") -> QuestionResult:
    return QuestionResult(qid, "grey", why)


def is_lender(d: ScreenerData) -> bool:
    text = f"{d.broad_industry} {d.industry}".lower()
    return d.has_deposits or any(w in text for w in LENDER_WORDS)


# ------------------------------------------------------------------ 1. growth
def score_growth(d: ScreenerData) -> QuestionResult:
    sales = d.sales
    if len(sales) < 8 or any(v is None for v in sales):
        return _grey("growth")
    previous, latest = sum(sales[:4]), sum(sales[4:])
    if previous <= 0:
        return _grey("growth")
    growth = round((latest / previous - 1) * 100, 1)
    if growth >= config.GROWTH_GREEN_MIN:
        status = "green"
    elif growth >= config.GROWTH_AMBER_MIN:
        status = "amber"
    else:
        status = "red"
    word = "down" if growth < 0 else "up"
    return QuestionResult(
        "growth", status,
        f"Sales {word} {abs(growth):.1f}% over the last 4 quarters vs the 4 before",
        [FactDraft("Sales, last 4 quarters vs the 4 before", pct(growth, signed=True), SOURCE, d.url,
                   f"{d.quarter_labels[-1]} quarter" if d.quarter_labels else "")],
    )


# ------------------------------------------------------------------ 2. efficiency
def score_efficiency(d: ScreenerData) -> QuestionResult:
    if d.roce is None:
        return _grey("efficiency")
    roce = round(d.roce, 1)
    if roce >= config.ROCE_GREEN_MIN:
        status = "green"
    elif roce >= config.ROCE_AMBER_MIN:
        status = "amber"
    else:
        status = "red"
    as_of = f"{d.quarter_labels[-1]} quarter" if d.quarter_labels else ""
    facts = [FactDraft("Return on capital (ROCE)", pct(roce), SOURCE, d.url, "Latest year")]
    text = f"Return on capital {pct(roce)}"
    if d.opm is not None:
        text += f", profit margin {pct(d.opm, 0)}"
        facts.append(FactDraft("Profit margin (operating), latest quarter", pct(d.opm, 0), SOURCE, d.url, as_of))
    return QuestionResult("efficiency", status, text, facts)


# ------------------------------------------------------------------ 3. debt
def score_debt(d: ScreenerData) -> QuestionResult:
    if is_lender(d):
        return _grey("debt", "Doesn't apply to lenders, because borrowing is their business.")
    if d.borrowings is None or d.equity_capital is None or d.reserves is None:
        return _grey("debt")
    net_worth = d.equity_capital + d.reserves
    as_of = d.balance_as_of
    detail = f"borrowings {crore(d.borrowings)}, owners' money {crore(net_worth)}"
    if net_worth <= 0:
        return QuestionResult(
            "debt", "red", f"The owners' money in the business is negative ({crore(net_worth)})",
            [FactDraft("Equity + reserves (owners' money)", crore(net_worth), SOURCE, d.url, as_of),
             FactDraft("Borrowings", crore(d.borrowings), SOURCE, d.url, as_of)],
        )
    ratio = round(d.borrowings / net_worth, 2)
    if ratio < config.DEBT_GREEN_MAX:
        status = "green"
    elif ratio <= config.DEBT_AMBER_MAX:
        status = "amber"
    else:
        status = "red"
    return QuestionResult(
        "debt", status, f"Borrowings are {ratio:.2f}× the owners' money ({detail})",
        [FactDraft("Borrowings ÷ (equity + reserves)", f"{ratio:.2f}×", SOURCE, d.url, as_of),
         FactDraft("Borrowings", crore(d.borrowings), SOURCE, d.url, as_of),
         FactDraft("Equity + reserves (owners' money)", crore(net_worth), SOURCE, d.url, as_of)],
    )


# ------------------------------------------------------------------ 4. price
def score_price(d: ScreenerData) -> QuestionResult:
    if d.pe is None:
        if d.price is None:
            return _grey("price")
        # Screener leaves P/E blank when the company has no profit per share.
        return QuestionResult(
            "price", "red", "The company is making a loss, so P/E can't be worked out",
            [FactDraft("P/E (price ÷ yearly profit per share)", "Not available: loss-making", SOURCE, d.url, "Latest")],
        )
    median = d.median_peer_pe
    if median is None:
        return _grey("price", f"Too few similar companies to compare (P/E is {d.pe:.1f}).")
    ratio = round(d.pe / median, 2)
    if ratio <= config.PE_GREEN_MAX_RATIO:
        status = "green"
    elif ratio <= config.PE_AMBER_MAX_RATIO:
        status = "amber"
    else:
        status = "red"
    return QuestionResult(
        "price", status,
        f"P/E {d.pe:.1f} vs {median:.1f} for similar companies ({ratio:.2f}× theirs)",
        [FactDraft("P/E (price ÷ yearly profit per share)", f"{d.pe:.1f}", SOURCE, d.url, "Latest"),
         FactDraft(f"Median P/E of {len(d.peer_pes)} similar companies", f"{median:.1f}", SOURCE, d.url, "Latest")],
    )


# ------------------------------------------------------------------ 5. news
@dataclass
class NewsLabel:
    about_company: bool
    tone: str      # good | bad | neutral
    serious: bool


def score_news(labels: list[NewsLabel] | None) -> QuestionResult:
    """None means the news source or the AI labeller failed: grey, not green."""
    if labels is None:
        return _grey("news", "Couldn't fetch this right now.")
    relevant = [x for x in labels if x.about_company]
    if any(x.serious for x in relevant):
        return QuestionResult("news", "red", "Serious negative news in the last 30 days")
    if any(x.tone == "bad" for x in relevant):
        return QuestionResult("news", "amber", "Some negative news in the last 30 days")
    return QuestionResult("news", "green", "Nothing negative in the last 30 days")


# ------------------------------------------------------------------ overall
def overall_label(results: list[QuestionResult], lender: bool = False) -> dict:
    """Looks solid: no red and 3+ green. Be careful: 2+ red, or news red. Otherwise Mixed.
    Grey questions count for nothing. Lenders are capped at Mixed."""
    statuses = {r.id: r.status for r in results}
    reds = sum(1 for s in statuses.values() if s == "red")
    greens = sum(1 for s in statuses.values() if s == "green")
    if reds >= 2 or statuses.get("news") == "red":
        code = "be_careful"
    elif reds == 0 and greens >= 3:
        code = "mixed" if lender else "looks_solid"
    else:
        code = "mixed"
    return {"code": code, "display": {"looks_solid": "Looks solid", "mixed": "Mixed", "be_careful": "Be careful"}[code]}


def score_all(d: ScreenerData, news: list[NewsLabel] | None) -> tuple[list[QuestionResult], dict]:
    results = [score_growth(d), score_efficiency(d), score_debt(d), score_price(d), score_news(news)]
    return results, overall_label(results, lender=is_lender(d))
