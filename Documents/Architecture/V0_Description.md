# Stock Analyst (India) — v0 Plan for All Three Phases

Nov 25, 2026 · @Subhan

## Why v0, and how to build it

The earlier docs describe the finished product: verdict rules, thresholds, alerts, a scanner. They're a good picture of where this could end up, but they ask you to trust buy and sell rules before you can judge them. v0 turns that around.

**v0 explains; it doesn't decide.** Every phase shows plain facts with their sources and a short summary, so you learn what the numbers mean by looking at stocks you know. Buy and sell advice comes in a later version, once you can read a report and say whether a call makes sense.

### Rules for every v0 screen

- **Plain words.** Every number has a one-line "what this means" next to it.
- **Every number links to where it came from.**
- **No buy or sell advice.** The strongest wording is an overall label: Looks solid, Mixed or Be careful.
- **Runs when you ask.** No background jobs, no queues; a Refresh button is enough.
- **This is a research aid, not financial advice.** That line appears on every screen.

### Build order

| Step | Phase | What you get | Rough effort |
| --- | --- | --- | --- |
| 1 | Phase 1 v0: Stock report | Type a stock, get the five questions and a summary | 1–2 weekends |
| 2 | Phase 2 v0: My stocks | Your holdings in one list, each with its report and a "look at this" flag | 1 weekend |
| 3 | Phase 3 v0: Market today | What the market did today, the main headlines, and which of your stocks are in the news | 1 weekend |

Don't start a step until the one before it works on stocks you know. Use Phase 1 for a week or two before moving on: that's when you'll learn the most.

## The five questions (used by every phase)

This is the whole analysis in v0. Each question gets a colour, the number behind it, a one-line meaning and a link to the source. All numbers come from the stock's Screener page, except question 5, which uses news.

| # | Question | What we measure | Green | Amber | Red |
| --- | --- | --- | --- | --- | --- |
| 1 | Is the business growing? | Sales over the last 4 quarters vs the 4 quarters before | 10% or more | 0–10% | Shrinking |
| 2 | Does it make money efficiently? | Return on capital (ROCE): profit earned on the money invested in the business. Profit margin is shown beside it | 15% or more | 10–15% | Below 10% |
| 3 | Can it handle its debt? | Borrowings ÷ the owners' money in the business (equity + reserves) | Below 0.5 | 0.5–1 | Above 1 |
| 4 | Is the share price expensive? | P/E (price ÷ yearly profit per share) vs the middle P/E of similar companies on Screener | At or below similar companies | Up to 1.5× theirs | Above 1.5×, or the company is making a loss |
| 5 | Is anything bad happening? | Headlines from the last 30 days | Nothing negative | Some negative news | Serious news: fraud, a regulator's order, a loan default, an auditor quitting |

**What each one means, in one line (shown on the screen):**

1. A company that sells more each year usually has something people want.
2. A good business turns the money put into it into profit; 15 rupees a year on every 100 invested is healthy.
3. Too much borrowing makes a company fragile when times are bad.
4. Even a great company can be a poor buy if the price already assumes everything goes right.
5. Numbers only change every quarter; news tells you what's happening now.

**Overall label**

- **Looks solid:** no red, and at least 3 greens.
- **Be careful:** 2 or more reds, or question 5 is red.
- **Mixed:** everything else.

**Special cases**

- **Banks and other lenders:** question 3 shows "doesn't apply to lenders", because borrowing is their business. Their label can be at most Mixed in v0.
- **Missing data** (a new listing, too few similar companies): that question shows grey, "not enough data", and doesn't count toward the label.

These cut-offs are simple starting points. Once you've looked at 20 or 30 stocks you know, change any that feel wrong; that's part of the learning.

## Phase 1 v0: Stock report

**Job:** type any NSE stock and, in under a minute, understand what the company does, whether its basics look healthy, and whether anything worrying is in the news.

### Screens

**1. Search**

- A search box that matches company names and NSE symbols.
- Below it, "Stocks you looked at": a plain list of earlier reports, newest first.

**2. Report**, top to bottom:

| Block | What it shows |
| --- | --- |
| Header | Company name, symbol, current price, today's change, "as of" time |
| Overall | The label (Looks solid / Mixed / Be careful) and one or two sentences on why, with source links |
| What the company does | 2–3 plain sentences |
| The five questions | Five rows: colour, question, the number, its one-line meaning, source link |
| Recent news | The 3 most important headlines from the last 30 days: outlet, date, a one-line summary, link |
| Footer | "Research aid, not financial advice" and when each source was last fetched |

### Data

| What | Source | How |
| --- | --- | --- |
| Company list for search | NSE equity list | Download the CSV once a week |
| Price, P/E, ROCE, description, quarterly sales, profit margin, balance sheet, similar companies | The stock's Screener.in page (consolidated) | Scrape when you open a report; keep it for 24 hours |
| News | Google News RSS search for the company name, trusted Indian outlets only, last 30 days | Fetch when you open a report |

### Logic

1. Fetch the Screener page and work out the five numbers with the rules above.
2. Fetch up to 20 headlines.
3. **One AI call** gets the headlines and returns, for each: about this company or not, good / bad / neutral, serious or not, and a one-line summary. Code turns those into question 5's colour.
4. Code picks the overall label.
5. **A second AI call** gets everything as numbered facts (F1, F2…) and writes "Overall" and "What the company does", citing fact numbers. It's told: use only these facts, no advice, plain words.
6. **A simple check:** every fact number it cites exists, and it doesn't use the words buy, sell or target. If the check fails, show the facts without the AI text.

### Done when

- [ ] Any NSE stock you type gets a report, or a clear message saying why it can't.
- [ ] Every number and sentence links to its source.
- [ ] You've read reports for 10 stocks you know, and the colours and labels make sense to you (or you've changed the cut-offs until they do).
- [ ] A report opens in under a minute.

## Phase 2 v0: My stocks

**Job:** see all your holdings in one place, each with its Phase 1 report, and know which ones deserve a closer look today.

### Screens

**1. Add or edit a holding:** stock, number of shares, average buy price. Nothing else.

**2. My stocks:** one row per holding.

| Column | What it shows |
| --- | --- |
| Stock | Name and symbol; tap to open its report |
| Shares and buy price | As you entered them |
| Value today | Shares × current price |
| Gain or loss | In ₹ and % |
| Label | Looks solid / Mixed / Be careful, from its report |
| Look at this | A flag, with the reason in a few words |

At the top: total invested, total value today, total gain or loss.

### The "Look at this" flag

A holding is flagged if any of these is true:

- its label is **Be careful**;
- its label got **worse** since the last refresh (for example Looks solid became Mixed);
- the price is **20% or more below** your buy price;
- a **serious** news item appeared since the last refresh.

The flag never says what to do. It says why the stock deserves a look, and the report gives the facts.

### Data

- **Your holdings:** saved locally (a small database file).
- **Everything else:** the same Phase 1 reports, refreshed with one "Refresh all" button (or once a day).

### One optional alert (last, only if the rest works)

A Telegram message when a holding gets a new flag: the stock, the reason, and a link to its report. At most one message a day per stock.

### Done when

- [ ] You've entered every stock you own.
- [ ] The totals match what your broker shows (within small price differences).
- [ ] Each row opens the right report.
- [ ] Flags appear for the right reasons when you test them (for example by entering a high buy price).

## Phase 3 v0: Market today

**Job:** in two minutes, know what the Indian market did today, the main reasons people are giving, and whether any of your stocks were in the news.

### Screen: Market today

| Block | What it shows |
| --- | --- |
| Market move | Nifty 50 and Sensex: level and today's change in % |
| What happened today | Up to 3 short points, each citing the headline it comes from |
| Top headlines | The 10 latest market headlines: outlet, time, link |
| Your stocks in the news | Headlines that mention a stock in My stocks, linked to its report |
| Watching | Stocks you've marked "watching" (no shares), each with its label and a link to its report |

**Watching** is the v0 watchlist: in My stocks, add a stock with no shares and it's listed here instead.

### Data

| What | Source |
| --- | --- |
| Nifty 50 and Sensex | yfinance (^NSEI and ^BSESN) |
| Market headlines | ET Markets RSS and Business Standard Markets RSS, last 24 hours |
| Your stocks | My stocks (Phase 2) |

### Logic

1. Fetch the two index moves and the last 24 hours of headlines; drop duplicates (same link, or nearly the same title).
2. **One AI call** gets the index moves and numbered headlines, and writes up to 3 points on what happened, each citing headline numbers. Same rules as Phase 1: only these facts, plain words, no advice. If the check fails, show the headlines without the points.
3. Code finds headlines that contain the name of one of your stocks.

### Done when

- [ ] The page loads with today's numbers and headlines.
- [ ] Every point links to a real headline that says it.
- [ ] Your stocks in the news picks up a stock you own on a day it's in the headlines (check a few days by hand).

## Tech setup

The smallest setup that does all three phases:

- **Backend:** one Python app (FastAPI or Flask). Libraries: requests and BeautifulSoup for Screener, feedparser for RSS, yfinance for the two indices.
- **Frontend:** a simple web page (or Streamlit if you want the fastest route). The mockup's Phase 1–3 screens are the guide.
- **Storage:** one SQLite file; the tables are listed under API contracts → Storage.
- **AI:** two kinds of call: labelling headlines (a small, cheap model) and writing summaries (a stronger model). Both get numbered facts and must cite them.
- **Being polite to Screener:** fetch a page only when a report is opened or refreshed, keep it for 24 hours, and wait a few seconds between pages on "Refresh all".

No background jobs, queues or schedulers. The only scheduled thing, and only if you want it, is a once-a-day "Refresh all" for the Phase 2 alert.

## Locked data sources (v0)

Nothing outside this list is used in v0.

| # | Source | Address | What we take | Refresh | Phases |
| --- | --- | --- | --- | --- | --- |
| 1 | NSE equity list | `https://archives.nseindia.com/content/equities/EQUITY_L.csv` | Symbol, company name, series, ISIN (EQ and BE series only) | Weekly | 1, 2 |
| 2 | Screener.in company page | `https://www.screener.in/company/{SYMBOL}/consolidated/`, or `/company/{SYMBOL}/` if there's no consolidated page | About text; Stock P/E and ROCE (top ratios); last 8 quarters of sales and operating margin; latest borrowings, equity capital and reserves; industry | When a report is opened or refreshed; kept 24 hours | 1, 2 |
| 3 | Screener.in peers | Loaded separately by the company page (check the exact request when building) | Each similar company's P/E | Same as 2 | 1, 2 |
| 4 | yfinance | `{SYMBOL}.NS`, `^NSEI`, `^BSESN` | Latest price, previous close, change % | On page open | 1, 2, 3 |
| 5 | Google News RSS | `https://news.google.com/rss/search?q="{company name}"+when:30d&hl=en-IN&gl=IN&ceid=IN:en` | Title, outlet, published time, link | When a report is opened or refreshed | 1, 2 |
| 6 | ET Markets RSS | `https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms` | Title, time, link, short description | On page open | 3 |
| 7 | Business Standard Markets RSS | `https://www.business-standard.com/rss/markets-106.rss` | Title, time, link, short description | On page open | 3 |
| 8 | AI model API | A small model for labelling headlines; a stronger model for writing | Labels and short text, always citing fact or headline numbers | Per report or page | 1, 2, 3 |
| 9 | Telegram Bot API (optional) | `sendMessage` | Sends the Phase 2 alert | Once a day at most per stock | 2 |
| 10 | You | The Add holding form | Stock, shares, average buy price, watching yes/no | When you edit | 2, 3 |

**Trusted outlets for stock news (source 5):** Economic Times, Business Standard, Mint, Moneycontrol, The Hindu BusinessLine, Financial Express, CNBC-TV18, Reuters. Items from any other outlet are dropped.

**Why yfinance in Phase 1:** it gives today's change, which Screener's page doesn't reliably show. Screener's price is the fallback if yfinance fails.

**If a source fails:** the report still opens. The affected question shows grey ("couldn't fetch this right now"), and the footer names the source and when it last worked.

## API contracts (v0)

The screens talk to the backend only through these endpoints. All responses are JSON. Every value the screen shows arrives ready to display, so the frontend does no maths.

### Endpoints

| Phase | Method and path | Request | Response |
| --- | --- | --- | --- |
| 1 | `GET /api/stocks/search?q={text}` | Part of a name or symbol | Up to 10 `{symbol, name}` |
| 1 | `GET /api/reports/{symbol}?refresh=false` | `refresh=true` skips the 24-hour cache | `Report` |
| 1 | `GET /api/reports/recent` | — | List of `{symbol, name, label, generated_at}`, newest first |
| 2 | `GET /api/holdings` | — | `Holdings` |
| 2 | `POST /api/holdings` | `{symbol, shares, buy_price, watching}` | The saved row |
| 2 | `PUT /api/holdings/{symbol}` | Same fields | The saved row |
| 2 | `DELETE /api/holdings/{symbol}` | — | `{deleted: true}` |
| 2 | `POST /api/refresh-all` | — | `{refreshed: [symbols], failed: [{symbol, reason}], new_flags: [symbols]}` |
| 3 | `GET /api/market/today` | — | `MarketToday` |

Errors always look like `{"error": {"code": "not_found" | "source_unavailable" | "bad_request", "message": "plain sentence"}}`.

### Report (Phase 1)

```json
{
  "symbol": "ABB",
  "name": "ABB India Ltd",
  "generated_at": "2026-11-25T10:15:00+05:30",
  "price": {"display": "₹6,412", "change_display": "+1.2%", "direction": "up", "as_of": "25 Nov, 3:30 pm"},
  "label": {"code": "mixed", "display": "Mixed"},
  "overall": {"text": "...", "cites": ["F1", "F4"]},
  "about": {"text": "...", "cites": ["F9"]},
  "questions": [
    {"id": "growth", "question": "Is the business growing?", "status": "green",
     "value_display": "Sales up 18% on a year ago", "meaning": "A company that sells more each year usually has something people want.",
     "cites": ["F1"]}
  ],
  "news": [
    {"id": "N1", "title": "...", "outlet": "Mint", "date_display": "21 Nov", "summary": "...", "tone": "good", "url": "https://..."}
  ],
  "facts": [
    {"id": "F1", "label": "Sales, last 4 quarters vs the 4 before", "value_display": "+18%", "source": "Screener.in", "url": "https://...", "as_of": "Sep 2026 quarter"}
  ],
  "sources": [{"name": "Screener.in", "fetched_at_display": "25 Nov, 10:14 am", "ok": true}],
  "ai_text": true,
  "disclaimer": "Research aid, not financial advice."
}
```

- `questions` always has 5 items, in the order growth, efficiency, debt, price, news. `status` is green, amber, red or grey.
- Every `cites` entry is an id from `facts` (F…) or `news` (N…).
- `ai_text: false` means the AI text failed the check; `overall` and `about` are then empty and the screen shows the facts only.

### Holdings (Phase 2)

```json
{
  "totals": {"invested_display": "₹4,20,000", "value_display": "₹4,86,300", "gain_display": "+₹66,300 (+15.8%)", "direction": "up"},
  "rows": [
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance", "watching": false,
     "shares": 50, "buy_price_display": "₹720", "value_display": "₹46,000",
     "gain_display": "+₹10,000 (+27.8%)", "direction": "up",
     "label": {"code": "mixed", "display": "Mixed"},
     "flag": {"on": true, "reason": "Label went from Looks solid to Mixed"},
     "report_updated_display": "25 Nov"}
  ]
}
```

Rows with `watching: true` have no shares, value or gain; Phase 3 lists them under Watching.

### MarketToday (Phase 3)

```json
{
  "as_of": "25 Nov, 3:30 pm",
  "indices": [{"name": "Nifty 50", "value_display": "24,310", "change_display": "-0.6%", "direction": "down"}],
  "points": [{"text": "...", "cites": ["H2", "H5"]}],
  "headlines": [{"id": "H1", "title": "...", "outlet": "ET Markets", "time_display": "2:10 pm", "url": "https://..."}],
  "your_stocks_in_news": [{"symbol": "ABB", "name": "ABB India", "headline_id": "H3"}],
  "watching": [{"symbol": "TITAN", "name": "Titan", "label": {"code": "looks_solid", "display": "Looks solid"}}],
  "ai_text": true
}
```

### AI calls (inside the backend)

| Call | Input | Output |
| --- | --- | --- |
| Headline labeller (Phase 1) | Company name; numbered headlines `{id, title, outlet, date}` | For each id: `{about_company: yes/no, tone: good/bad/neutral, serious: yes/no, summary}` |
| Report writer (Phase 1) | Numbered facts and news, the five statuses, the label | `{overall: {text, cites}, about: {text, cites}}` |
| Market writer (Phase 3) | Index moves; numbered headlines | `{points: [{text, cites}]}`, at most 3 |

The check on every writer output: valid JSON, every `cites` id exists, at least one citation per sentence, and none of the words buy, sell, target or recommend.

### Storage (one SQLite file)

| Table | Columns |
| --- | --- |
| companies | symbol, name, series, isin, updated\_at |
| page\_cache | url, body, fetched\_at |
| reports | symbol, generated\_at, label, report\_json |
| holdings | symbol, shares, buy\_price, watching, added\_at |
| flags\_sent | symbol, reason, sent\_at |

## Not in v0

These come later, in this order, once v0 is in daily use. The detailed designs are already written in [Intelligence Layer (v1)](https://claude.ai/artifact/Gdr8fKTySpZdGFffEDEP4s), [Data Layer (v1)](https://claude.ai/artifact/SVFm7CsFiCa4zrAjp4xwe9) and [Intelligence Layer Architecture](https://claude.ai/artifact/3c5aWbovAnnNFS5x32PJXr); treat them as the target for later versions.

1. **Buy / Watch / Avoid and Hold / Trim / Exit advice**, with rules you've checked against reports you trust.
2. **Exact moves for your holdings:** how many shares, and when, based on tax.
3. **Buy dates, lots and tax estimates.**
4. **More detail in the report:** trends over time, who owns the company, company filings from NSE.
5. **Sector moves and fund flows** on the Market page.
6. **"Worth a look"** suggestions from the Nifty 500.
7. **Background refresh,** report history and more alert types.

## Glossary

| Term | Plain meaning |
| --- | --- |
| NSE | National Stock Exchange of India, where these stocks trade |
| Symbol | A stock's short code on NSE, such as RELIANCE |
| Nifty 50 / Sensex | The two main market scores: the combined price of India's 50 (Nifty) or 30 (Sensex) biggest companies |
| Sales (revenue) | Money the company takes in from customers |
| Profit margin | Out of every ₹100 of sales, how much is left as profit |
| ROCE | Return on capital: profit each year on every ₹100 invested in the business |
| Borrowings | Money the company owes to lenders |
| Equity + reserves | The owners' own money in the business, including past profits kept |
| P/E | Price ÷ yearly profit per share: how many years of today's profit you pay for |
| Similar companies (peers) | Companies in the same line of business, as listed on Screener |
| Consolidated | Figures for the whole group, including companies it owns |
| Quarter | Three months; Indian companies report results every quarter |
| Lender / NBFC | A bank or a finance company that lends money |
| RSS | A simple feed of a news site's latest headlines that code can read |
