# Stock Analyst (India) — PRD v1

Nov 21, 2026 · @Subhan

## Overview

Stock Analyst is a personal AI research analyst for Indian stocks (NSE) that tells you, in plain language, what is happening, why, and what to do next, with a source for every fact.

- **Who it's for:** one investor (the owner) with a busy life who wants to hand off the analysis, not read more data. Personal use first; a client version may follow later (see Risks).
- **The problem:** strategic moves get missed because news, results or price signals went unnoticed, and connecting them takes time nobody has.
- **The guiding principle:** don't show more financial data; explain what the data means and whether it should change a decision.
- **The core loop:** Market spots something → Research checks it → you buy → Portfolio watches it → you're told when something changes.

The product is built in three phases, one at a time, each finished and in daily use before the next starts: **Stock Investigation**, then **Portfolio Intelligence**, then **Market Intelligence**.

## Product principles

These five rules apply to every screen, report and message.

1. **Plain language everywhere.** Every label says what it means ("Price you pay for ₹1 of yearly profit"), with the technical term in small grey text beside it ("P/E"). No jargon in sentences: "the Jul–Sep quarter", not "Q2 FY27".
2. **Every fact has a source.** Each number or news claim carries a numbered citation (E1, E2…) that links to where it came from, with a date. The engine's interpretations are labelled **Our read**.
3. **Code computes, AI explains.** All numbers, ratios, technicals, tax and rule checks are calculated in code. The AI only explains verified numbers and never invents or calculates one.
4. **Honest when unsure.** The engine says "not enough evidence" instead of guessing, and keeps the last good version if a new one fails validation.
5. **Explicit actions.** Every report ends in a clear action: **Buy / Watch / Avoid** for stocks you don't own, **Add / Hold / Book profit / Trim / Exit** for stocks you own, with confidence and what would change it.

Answer first, reasoning on demand: each report shows five blocks; everything else sits behind one **Show full reasoning** button.

## Phases at a glance

The build order is Stock Investigation, then Portfolio Intelligence, then Market Intelligence; each phase reuses the one before and adds one question.

&#91;embedded content: build order · 3 phases, one shared layer\]

The stock report from Phase 1 is the core: Phase 2 adds your position on top of it, and Phase 3 feeds it new stocks to research.

## Phase 1 — Stock Investigation

Phase 1 answers **"Is this stock worth buying?"** for any NSE stock, in one five-block report.

**Screens**

1. **Research a stock:** a search box (NSE symbol or company name), a few quick picks, and a list of recent reports with their verdict and last-updated date.
2. **Stock report:** the five blocks below, then a **Show full reasoning** button.

**The report**

| Block | What it shows | Built from |
| --- | --- | --- |
| 1. Verdict | Buy / Watch / Avoid, one-line reason, confidence, and what would turn it into each other action | Rules engine + AI wording |
| 2. What the company does | 2–3 sentences and the revenue split by business | Screener.in "About" + AI summary |
| 3. Health & value | Six numbers, each with a plain label, the technical term, a flag (Good / OK / Watch / Expensive) and an **Our read** line | Screener.in |
| 4. Bull vs bear | Three cited reasons it could work, three cited things that could go wrong | Evidence pack + AI |
| 5. Recent news & announcements | Top 3 items this month, each tagged Announcement / News / Unconfirmed | NSE filings + stock news |

**Show full reasoning** opens: price trend (direction, distance from the year's high, buying vs selling pressure, trading activity), how the signals connect (agreements and conflicts, marked as timing not proof), more numbers, and the full numbered source list.

**Functional requirements**

- Search resolves a symbol or company name to one NSE company and its ISIN.
- A report is built in under 60 seconds the first time and cached; it rebuilds only when new results, an announcement or a material news item arrives.
- The six health numbers use a sector template (e.g. lenders show loan growth and bad loans instead of operating margin).
- Every claim in blocks 1, 4 and 5 has at least one valid citation, or the claim is dropped.
- The Verdict states what would turn it into Buy, Watch or Avoid, as a specific price or metric threshold.

**Acceptance criteria**

- [ ] Reports work for any 20 Nifty 500 stocks, including at least 3 banks or lenders.
- [ ] No report shows a citation that doesn't exist in its evidence pack.
- [ ] No number on the report differs from Screener.in or the NSE filing it cites.
- [ ] Every label passes the plain-language check: a non-investor can say what each one means.

## Phase 2 — Portfolio Intelligence

Phase 2 answers **"What should I do about the stocks I already own?"** by adding your position to the Phase 1 report.

**Screens**

1. **Add your holdings:** a manual entry form per stock (NSE symbol, shares, average price paid, buy date). Optional CSV upload later; a broker API is out of scope for now.
2. **My portfolio:** three totals (worth today, total gain, today's change), then **Needs your attention** (stocks whose action changed since your last visit), then **No change since your last visit**. Each row shows shares, value, gain, the action and one plain sentence on why.
3. **Report for a stock you own:** the Phase 1 report plus a **Your position** strip at the top. Block 1 becomes **What to do**; block 4 becomes **Keep or sell some?**
4. **Telegram message:** see Alerts.

**Your position strip**

- Shares owned, price paid, worth now, gain (₹ and %), share of your money.
- **Tax tip:** whether selling today is short-term (20%) or long-term (12.5%, first ₹1.25 lakh a year tax-free), and the date it turns long-term.

**What to do**

- Action: Add / Hold / Book profit / Trim / Exit, with confidence and "changed on / was".
- **Suggested move:** a specific share count and timing ("sell 12 of your 50 shares on or after 3 Jan"), and an earlier trigger ("sooner if it closes below ₹925").
- What would move it to each neighbouring action.
- Behind **Show full reasoning:** a profit-taking checklist (gain threshold, safety price level, expensive for itself, too much money in one stock, lower tax date close).

**Functional requirements**

- Holdings are stored locally; editing a holding rebuilds that stock's position and action.
- Every action change is logged with date, price and reason (the call log).
- Tax rates and rule thresholds live in a config file, not in code.

**Acceptance criteria**

- [ ] For two weeks of daily use, every holding has a current action and no uncited claim.
- [ ] Every action change appears in Needs your attention and in Telegram within 1 hour.
- [ ] Gain, value and tax numbers match a manual spreadsheet check to the rupee.

## Phase 3 — Market Intelligence

Phase 3 answers **"What's happening in the market, and what should I look at?"** and closes the loop back to Research and Portfolio.

**Screens**

1. **Today in the market** (the dashboard):
   - A one-line headline and the Nifty 50, Nifty 500 and Sensex moves.
   - **Why the market moved:** three numbered reasons in plain words, each cited.
   - **Sectors yesterday:** a simple bar list of sector moves.
   - **What this means for you:** which holdings were affected and whether anything needs doing.
   - **Worth a look:** about five Nifty 500 stocks you don't own with unusual moves or big news, each with one line on why, a short "could be good / could be bad", and **Research it** and **+ Watchlist** buttons.
2. **Watchlist:** stocks you don't own yet. **Turned Buy** at the top, then **Still watching**, each saying what it's waiting for ("price below ₹4,700").
3. **Telegram:** an optional morning briefing, plus a message when a watchlist stock turns Buy.

**Functional requirements**

- The scan covers the Nifty 500 list, refreshed after each half-yearly rebalance.
- "Unusual" means: a price move or volume well outside the stock's normal range, or a high-materiality announcement. Thresholds live in config.
- Market-wide news is deduplicated across outlets; the AI picks the 5–8 stories that matter and tags each with its sector.
- A market-wide story that names one of your stocks also appears on that stock's report, merged so it isn't counted twice.
- Broker calls are labelled as opinions and never counted in a verdict.

**Acceptance criteria**

- [ ] The briefing is ready by 08:45 IST on every trading day for two weeks.
- [ ] Each "Why the market moved" reason cites at least one source.
- [ ] Worth a look never lists a stock you already own.

## Data sources (locked)

Fundamentals come from Screener.in; news comes from four sources, two for the market and two per stock.

| Data | Source | How | Refresh | Used from |
| --- | --- | --- | --- | --- |
| Fundamentals: 10 years annual, recent quarters, ratios, shareholding, "About" | **Screener.in** company pages (consolidated, standalone as fallback) | Scraped gently, cached | Weekly, and after a results filing | Phase 1 |
| Company announcements and results | **NSE filings** (RSS + per-stock announcements, via `nselib`) | Feed + endpoint | Every 5 min in market hours | Phase 1 |
| Stock-specific news | **Google News RSS**, one search per stock limited to Moneycontrol, ET, Business Standard, Mint, BusinessLine, Reuters, with `when:7d` | RSS | Every 15 min in market hours | Phase 1 |
| Prices, history, technicals | **yfinance** (`.NS` tickers) | Library | Daily close; 15 min in market hours | Phase 1 |
| Market-wide news | **ET Markets RSS** + **Business Standard Markets RSS** | RSS | Every 15 min | Phase 3 |
| Index levels, sector indices, end-of-day prices for all stocks | **NSE via `nselib`** (all-indices data, bhavcopy) | Library | After market close | Phase 3 |
| Foreign/local fund flows, market fear gauge | **NSE via `nselib`** (FII/DII, India VIX) | Library | Daily | Phase 3 |
| Oil price, rupee vs dollar | **yfinance** (`BZ=F`, `INR=X`) | Library | Daily | Phase 3 |
| Nifty 500 list, NSE company list (symbol, name, ISIN) | **NSE CSV downloads** | File | After each rebalance / weekly | Phases 1 and 3 |
| Your holdings | **Manual entry** | Form | On edit | Phase 2 |
| Tax rates, rule thresholds | **Config file** | File | After each Budget | Phase 2 |
| Alerts | **Telegram Bot API** | API | On trigger | Phases 2 and 3 |

**Feed URLs**

- ET Markets: `https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms`
- Business Standard Markets: `https://www.business-standard.com/rss/markets-106.rss`
- Google News search: `https://news.google.com/rss/search?q=<query>&hl=en-IN&gl=IN&ceid=IN:en`

**Backup:** IndianAPI.in (financials, shareholding, company news) if Screener.in or Google News fails.

## Intelligence layer

One shared pipeline turns raw data into a cited report; code does every calculation and a validator blocks anything the evidence can't support.

&#91;embedded content: report pipeline · 7 steps, 1 safety net\]

The AI sees only the evidence pack, and every claim it makes must point to an evidence ID.

- **Evidence pack:** every citable fact (a number, a filing, a news item) is stored with an ID, its source, its date and its reporting period.
- **Rules engine:** sets the action from computed checks: valuation against the stock's own history, growth, margins, price levels, and, for held stocks, gain, concentration and tax timing. Thresholds live in config.
- **AI synthesis:** writes the one-line reason, the **Our read** lines, bull and bear points and "what would change the call" in plain language. It cannot change the action the rules set.
- **Validation:** rejects any output that cites an unknown ID, states a number not in the evidence, or skips a required field. Evidence strength is computed by code, not self-rated by the AI.
- **Sticky actions:** an action changes only when new evidence passes a threshold (for example, a results filing plus a confirming price move), so it doesn't flip with every headline.
- **Call log:** every version of every report is saved with its date, price and action, which becomes the track record after three months.

## Alerts

Telegram messages go out only when something needs you, so a typical week brings a handful at most.

| Trigger | Phase | Example |
| --- | --- | --- |
| A held stock's action changes | 2 | "Bajaj Finance: Hold → Book profit" |
| A high-materiality announcement for a held stock | 2 | "Infosys: board outcome, sales forecast lowered" |
| A "what would change the call" trigger is hit (price level, metric threshold, a rumour confirmed by a filing) | 2 | "Closed below ₹925: Trim now" |
| A watchlist stock turns Buy | 3 | "Polycab: Watch → Buy" |
| Morning briefing (optional, once a day) | 3 | "A down day, led by banks" |
| System problem: a source failing for over 2 hours | 2 | "Screener.in not responding since 10:15" |

**Every message carries:** the stock, the change (old → new), a reason in two plain sentences, the suggested move when there is one, numbered sources with dates, and a **See why** link to the report.

**Limits:** at most one message per stock per day unless the action changes again; related events are merged into one message; nothing outside 08:00–22:00 IST except a stop-level trigger.

## Non-functional requirements

The app runs on one machine for one user, so the priority is being gentle with free sources and never showing stale data as fresh.

- **Refresh cadence:** as in the data sources table. Outside market hours (09:15–15:30 IST), feeds are checked every 30 minutes.
- **Caching:** one local database (SQLite) holds every fetched page, feed item and computed result, with its source and fetch time. Nothing is re-fetched while a cached copy is still fresh.
- **Being a polite client:** about one Screener.in page every 2–3 seconds; one NSE session with reused cookies and 1–2 seconds between calls; Google News searches spaced about 1 second apart.
- **Freshness labels:** every number shows its "as of" date or quarter; a quarterly figure is never shown as if it were live.
- **Failure handling:** if a source fails, the last good data stays on screen with its date, and a failed AI run never overwrites the last good report.
- **AI cost:** the AI runs only when a stock's evidence changes past a threshold, not on every refresh.
- **Speed:** a cached report opens in under 2 seconds; a fresh one builds in under 60 seconds.
- **Privacy:** holdings stay on the local machine; only stock symbols leave it, in data requests.

## Out of scope

These stay out of all three phases unless this PRD is revised.

- Automatic trading or placing orders
- Intraday trading signals and real-time streaming
- Price predictions and backtesting
- Options and derivatives analysis
- Portfolio optimisation algorithms
- Social media sentiment
- Broker API sync for holdings (manual entry for now)
- The **Ask your analyst** chat (deferred until after Phase 3)
- A combined India + US portfolio
- Multiple users, logins or sharing

## Risks and open questions

The biggest risk is that the free sources break or block requests; every one has a fallback, and the app keeps showing the last good data with its date.

| Risk | Effect | Mitigation |
| --- | --- | --- |
| Screener.in changes its page layout | Fundamentals stop updating | Parse by section heading, alert on parse failure, fall back to IndianAPI.in |
| NSE blocks requests | No new announcements | One session, reused cookies, slow polling; Google News still carries most results stories |
| Google News throttles or changes its feed | Fewer stock-specific stories | Space requests; fall back to IndianAPI.in company news |
| yfinance breaks or lags | Prices stale | Fall back to NSE end-of-day data |
| Paywalled stories arrive as headline + snippet only | Thin news evidence | The AI never claims more than the snippet; numbers come from filings |
| AI cites something wrong | Wrong reason shown | Citation validator rejects unknown IDs and numbers not in the evidence pack |
| Explicit actions are wrong | A bad decision | Confidence on every action, call log reviewed after 3 months, you decide every trade |

**Open questions**

- How should a stock with no news in 7 days be shown: "no news" or a longer window?
- Should the Phase 1 verdict use one time horizon or show a short-term and a long-term view?
- What gain level should trigger Book profit by default (the mockup uses +30%)?

**What changes for a client version**

- Scraped and unofficial sources (Screener.in, NSE pages, yfinance, Google News) need licensed replacements; some feeds carry personal-use-only notices.
- Explicit Buy / Sell / Trim actions given to someone else may fall under SEBI's rules for research analysts; get this reviewed first.
- Holdings move from manual entry to a broker API, with per-user storage and login.

## Success measures and definition of done

A phase is done when you use it daily for two weeks without needing to check another site for that job.

| Phase | Done when | Measured by |
| --- | --- | --- |
| 1. Stock Investigation | You research a stock here instead of on Screener, Moneycontrol or Google | Every acceptance check in Phase 1 passes; 20 stocks tested, 3 of them lenders |
| 2. Portfolio Intelligence | You never hear about an important event for a holding somewhere else first | Zero missed material announcements over 2 weeks; every action change reaches Telegram within 1 hour |
| 3. Market Intelligence | The morning briefing replaces your market news reading | Briefing on time every trading day for 2 weeks; at least one Worth a look stock researched per week |

**Longer-term measures (after 3 months of the call log)**

- Share of actions that, looking back, you'd have followed.
- How often Book profit and Trim calls beat simply holding over the following 3 months.
- Number of uncited or wrong claims found (target: zero).
