# Stock Analyst (India) — Data Layer (v1)

Nov 23, 2026 · @Subhan

This doc locks the data layer for v1: the sources, the records it stores and hands to the intelligence layer, and what is deliberately left for v2. The overall design lives in [Stock Analyst (India) — Intelligence Layer Architecture](https://claude.ai/artifact/3c5aWbovAnnNFS5x32PJXr).

## Locked sources

The data layer fetches and stores; it never interprets. Every record it keeps carries four fields so any fact can be cited later: **source**, **source link**, **fetched at** and **as of** (the date or period the fact is about).

| Source | What we take from it | How we get it | Refresh (held + watchlist) |
| --- | --- | --- | --- |
| Screener.in (consolidated page, standalone if none) | Description, quarterly and annual results, balance sheet, cash flow, ratios, shareholding, peers, industry, document links, Screener's P/E | Scraped HTML, no login | Weekly, and again the day after a results filing |
| yfinance | 5 years of daily prices, latest price, **P/E**, EPS, market cap, splits and dividends; Nifty 50, Sensex, Brent crude, rupee, S&P 500 | Python library | Daily after close; latest price when a page opens |
| NSE via nselib | Bhavcopy with delivery %, 52-week highs and lows, index and sector index moves, FII/DII flows, India VIX, equity list, Nifty 500 list, bulk and block deals, event calendar, NSE daily P/E file | Python library | Daily after close |
| NSE website (JSON, cookie session) | Company announcements with attachments, corporate actions, insider trades, promoter pledges | Direct requests, gentle polling | Announcements every 15–30 min in market hours; the rest daily |
| Google News RSS | Stock news from trusted outlets only, last 7 days | RSS search per stock | Every 1–2 hours |
| ET Markets RSS + Business Standard Markets RSS | Market-wide news | RSS | Every 30 min |
| You | Holding lots, watchlist, settings | Manual entry | When you edit |
| IndianAPI.in | Backup only, when a primary source fails | API | Only on failure |

**P/E rule:** yfinance's trailing P/E is the primary value. Screener's P/E is stored beside it as a cross-check. If yfinance's is missing, or the two differ by more than 15%, the report uses Screener's and marks it.

## Fetch tiers

| Tier | Which stocks | What gets fetched |
| --- | --- | --- |
| A | Stocks you hold + your watchlist | Everything, on the refresh times above |
| B | A stock you search for | Everything once when you open it, kept for 7 days |
| C | The Nifty 500 | Free NSE end-of-day files only; Screener only for the daily shortlist (see the scan method below) |

**One rule:** signals and verdicts use the daily close only. The latest price is for the header and the portfolio strip, so actions never flip during the day.

## Data contracts: what the data layer hands to the intelligence layer

These are the records the data layer stores. Values are stored as the source gives them (Screener figures in ₹ crore, periods as end dates such as 2026-09-30). Conversions and plain labels happen later, in the normalizer.

**Reference**

| Record | Key | Fields | Source | Refresh |
| --- | --- | --- | --- | --- |
| Company | symbol | name, ISIN, other names, Screener page id, yfinance ticker, industry, is financial company, in Nifty 500, tier | NSE equity list, Screener, our alias table | Weekly |

**Prices and valuation**

| Record | Key | Fields | Source | Refresh |
| --- | --- | --- | --- | --- |
| DailyPrice | symbol + date | open, high, low, close, volume, delivery % | yfinance (history), NSE bhavcopy (delivery %) | Daily |
| LatestQuote | symbol | price, previous close, change %, as-of time | yfinance | When a page opens |
| Valuation | symbol + date | P/E (yfinance), EPS for the last 12 months, market cap, Screener P/E, book value, dividend yield, ROCE, ROE | yfinance + Screener top ratios | Daily (yfinance), weekly (Screener) |
| CorporateAction | symbol + ex-date + type | split, bonus, dividend or rights; ratio or amount | NSE, yfinance | Daily |

**Fundamentals** (all from Screener; weekly and the day after a results filing)

| Record | Key | Fields |
| --- | --- | --- |
| QuarterlyResult | symbol + quarter end | sales, expenses, operating profit, operating margin %, other income, interest, depreciation, profit before tax, tax %, net profit, EPS |
| AnnualResult | symbol + year end | the same fields + dividend payout %; one extra row for the last 12 months |
| BalanceSheet | symbol + year end | equity capital, reserves, borrowings, other liabilities, fixed assets, work in progress, investments, other assets, total |
| CashFlow | symbol + year end | cash from operations, from investing, from financing; net cash flow |
| Ratios | symbol + year end | debtor days, inventory days, payable days, cash conversion cycle, working capital days, ROCE % |
| Shareholding | symbol + quarter end | promoters %, foreign funds %, local funds %, government %, public %, number of shareholders |
| Profile | symbol | about, key points, industry, peers (symbol, P/E, market cap, ROCE, latest quarter growth), document links |

**Filings and events**

| Record | Key | Fields | Source | Refresh |
| --- | --- | --- | --- | --- |
| Filing | NSE filing id | symbol, time, category, subject, text, attachment link, text pulled from the attachment | NSE announcements | 15–30 min in market hours |
| UpcomingEvent | symbol + date + purpose | results, board meeting, AGM | nselib event calendar | Daily |
| InsiderTrade | NSE record id | person, role (promoter, director), buy or sell, shares, value, date | NSE | Daily |
| BulkBlockDeal | date + symbol + party | party, buy or sell, shares, price | nselib | Daily |
| Pledge | symbol + date | share of promoter holding pledged % | NSE | Daily |

**News**

| Record | Key | Fields | Source | Refresh |
| --- | --- | --- | --- | --- |
| NewsItem | link hash | title, outlet, published time, link, snippet, which feed (stock search for a symbol, or market feed) | Google News RSS, ET Markets, Business Standard | 30 min to 2 hours |

**Market**

| Record | Key | Fields | Source | Refresh |
| --- | --- | --- | --- | --- |
| MarketDay | date | Nifty 50, Sensex, Bank Nifty close and change; each sector index's change; FII and DII net buying (₹ crore); India VIX; Brent; rupee; S&P 500 | nselib, yfinance | Daily |
| ScanDay | date + symbol | for each Nifty 500 stock: close, change %, volume vs its 20-day average, delivery %, new 52-week high or low, NSE P/E | nselib bhavcopy, 52-week report, P/E file | Daily |

**Your data**

| Record | Key | Fields |
| --- | --- | --- |
| HoldingLot | lot id | symbol, shares, buy price, buy date |
| WatchItem | symbol | added on, note |
| Settings | — | tax rates (20% short-term; 12.5% long-term above ₹1.25 lakh, after 12 months), action thresholds, alert limits, Telegram chat |

**System**

| Record | Key | Fields | Written by |
| --- | --- | --- | --- |
| FetchRun | run id | source, job, start, end, status, rows, error | Every fetch; feeds SystemStatus |
| ChangeEvent | event id | kind (new filing, new news, day closed, fundamentals updated, holding edited, market day closed), symbol, record ids, time | Data layer, read by the orchestrator |

The buy date on each holding lot is required. Without it the long-term tax countdown and the "sell on or after" date can't be worked out.

## Nifty 500 scan: event-first

Screener isn't crawled for all 500 stocks. The scan starts from free NSE end-of-day files and fetches Screener pages only for a short list.

1. **Every evening, scan all 500 using NSE files only:** price move, volume against the 20-day average, delivery %, new 52-week highs or lows, NSE P/E, and that day's filings (results, large orders, bulk deals).
2. **Shortlist about 20** with simple rules (to be set in the scanner logic step).
3. **Fetch Screener pages for the shortlist only** and keep them for 7 days. Many names repeat from day to day, so there are only a few new fetches each day.
4. **Run the full pipeline on the shortlist** and show the best 5 as "Worth a look".

This means roughly 5–20 Screener pages a day instead of 500 a week, and the fundamentals are always fresh for the stocks that show up.

Other options considered:

- **Weekly crawl of all 500:** heavy on Screener and up to a week stale.
- **Screener saved screens:** need a login, and scraping logged-in pages breaks easily.
- **IndianAPI.in in bulk:** kept as the fallback if Screener starts blocking.

## Financial companies in v1 (banks, NBFCs, insurers)

Bank and lender metrics are dropped for v1, so these companies get a **lite report** instead of no report:

- They're flagged by Screener's industry name.
- They show sales growth, profit growth, ROE and P/E. Debt and cash conversion are hidden, because they mislead for lenders.
- Confidence is capped at Low, with the note "Lender checks coming in v2".
- They're left out of "Worth a look".

A holding such as Bajaj Finance still appears in your portfolio with its price, gain, news and an action, at low confidence.

## What these decisions change in the read models

- **StockReport, business:** no revenue split; description only.
- **StockReport, six metrics:** sales growth, profit margin, return on capital, debt, cash conversion, and P/E vs the median of its Screener peers (no longer vs its own history).
- **StockReport, reasoning:** compares the stock only with the Nifty; the sector comparison is removed.
- **StockReport, new field:** coverage, either full or lite (financial company).
- **MarketBrief, sector moves:** kept, because it only lists each sector index's change and needs no stock-to-sector mapping.
- **MarketBrief, For you:** built from your holdings that appear in the day's market news and filings, not from sector moves.
- **MarketBrief:** no pre-open line.
- **AI writer output:** no "what others think" field.

## Deferred to v2

The running list of what v1 leaves out on purpose. Add to it whenever something is cut.

| Item | Why it's out of v1 | What v2 needs |
| --- | --- | --- |
| Revenue split by business segment | Segment results aren't on Screener's free plan | Segment data from the NSE results filing, or Screener Premium (₹4,999 a year) |
| Bank and lender metrics (bad loans, capital buffer, interest margin, loan growth) | Not on Screener's free company page | The bank's NSE results filing, plus a lender template |
| Stock-to-sector mapping (stock vs its sector, sector-based "For you") | No source maps companies to NSE sector indices | A hand-made table from Screener industry to sector index (about 40 rows) |
| P/E vs its own 5-year history | yfinance gives today's P/E only | Daily prices with EPS history, adjusted for splits and bonuses |
| Pre-open market direction (GIFT Nifty) | No reliable free feed | A paid or broker data feed |
| Broker targets ("what others think") | Not evidence under our rules, and no clean free source | Licensed consensus data, probably only for the client version |
| AI reading of concall transcripts | Kept out to limit scope | Links are already stored in the Profile record |
| "Ask your analyst" chat | Deferred earlier | Built on the same evidence packs |
| InsiderTrade and BulkBlockDeal fetches | The v1 intelligence logic doesn't use them, so they aren't fetched in v1 (bulk deals still count in the Nifty 500 scan through filings) | Turn the fetch back on when insider and deal signals are added |
