# Stock Analyst (India) — Intelligence Layer Architecture

Nov 22, 2026 · @Subhan

This doc covers what the intelligence layer receives, every component inside it, and exactly what it hands up to the UI. The UI never computes: it only displays the read models described at the end.

&#91;embedded content: intelligence layer · 4 stages between the data layer and the UI\]

Raw facts flow up from the data layer, through the four stages, and leave as fully formatted read models; the Decide stage uses rules only.

## What the intelligence layer receives from the data layer

The data layer only fetches and stores raw data; it does no thinking. It hands over:

- **Fundamentals snapshots:** per stock and per period, from Screener.in.
- **Daily prices and volume:** per stock, plus the Nifty and sector indices, from yfinance and NSE.
- **Announcements:** NSE filings with their text or PDF.
- **Raw news items:** from Google News, ET Markets and Business Standard.
- **Market context:** foreign and local fund flows, India VIX, oil price, rupee.
- **Reference lists:** NSE company list, Nifty 500 list, company name aliases.
- **Your data:** holdings, watchlist, config (thresholds, tax rates).

## The orchestrator

The orchestrator sits above the four stages and decides what runs and when.

- It watches for changes: a new filing, a new news item, the daily close, a fundamentals update, a holding edit.
- It queues only the affected stocks.
- It skips the AI step when nothing the report depends on has changed.

## Stage 1: Prepare

Turns raw data into clean facts.

| Component | Job |
| --- | --- |
| Normalizer | Consolidated figures, ₹ crore, April–March year labels, split and bonus adjustments, an "as of" date on every fact |
| Company matcher | Attaches each news item to the right company, rejecting look-alikes (HDFC Bank vs HDFC Life) |
| Story merger | Merges the same story from several outlets into one, and links stories that just repeat a filing |
| Event labeller (small AI model) | Labels each item: type, topic, direction, how much it matters, confirmed by a filing or not |

## Stage 2: Compute

All the maths happens here, in code.

| Component | Job |
| --- | --- |
| Metric engine | Growth, margins and their trends, return on capital, cash conversion, debt, P/E history and where today sits in it, price trend, return vs the Nifty, stock move vs sector move. For held stocks: gain, share of portfolio, days to long-term tax, tax if sold |
| Sector templates | Pick which metrics apply (general company vs bank or lender) |
| Signal scorer | Turns each metric into + / 0 / − with a plain label, rolls them into five scores (quality, growth, valuation, events, trend), and raises red flags |
| Connection finder | Finds agreements and conflicts between signals, and whether a move is company-specific or market-wide |

## Stage 3: Decide

Rules only, no AI.

| Component | Job |
| --- | --- |
| Rules engine | Picks the action: Buy / Watch / Avoid, or Add / Hold / Book profit / Trim / Exit for held stocks, plus the suggested move (shares, date) |
| Stickiness check | Compares with the last decision and allows a change only on a clear threshold cross or two confirming signals |
| Confidence | Calculated from how well the five scores agree, how complete the data is and how fresh it is |
| Trigger builder | Works out what would change the call: price levels, metric thresholds, a rumour confirmed |

## Stage 4: Explain

| Component | Job |
| --- | --- |
| Evidence pack builder | Gives every fact an ID, plain label, technical term, value, unit, period and source |
| AI writer | Writes the reason, "what the company does", the Our read lines, bull and bear points, connections and trigger wording |
| Validator | Rejects unknown citations, numbers not in the evidence, banned words and wrong structure; one retry, otherwise keep the last good report |
| Report assembler | Merges the computed values and the AI's text into the final read model |

## The store

- Every report version with its date, price and decision (this is the call log).
- The difference from the previous version, which drives "Needs your attention" and alerts.

## Modules that work across many stocks

- **Portfolio aggregator** (Phase 2): totals, today's change, and which holdings need attention, in order.
- **Scanner** (Phase 3): reads the Nifty 500 end-of-day prices and announcements and shortlists "Worth a look".
- **Market brief builder** (Phase 3): index, sector and fund-flow moves plus market news become three cited reasons, through the same AI writer and validator.
- **Watchlist monitor** (Phase 3): runs the normal pipeline on watchlist stocks.
- **Alert decider:** turns report changes into Telegram messages, within the frequency limits.

## What goes up to the UI: the read models

| Read model | Main fields | Screen |
| --- | --- | --- |
| StockReport | Header (name, symbol, price, change, as-of) · Verdict (action, previous action, changed on, confidence, reason, suggested move, triggers) · Position (held stocks only: shares, price paid, value, gain, weight, tax tip) · Business (summary, revenue split) · 6 metrics (label, term, value, flag, Our read, citation) · Bull ×3 and bear ×3 (text, citations) · News ×3 (type, title, outlets, date, citation) · Reasoning (price trend, connections, more numbers, checklist) · Sources · Freshness (fundamentals, price and news dates) · Evidence strength · Gaps | Report pages |
| PortfolioView | Totals (value, gain, today) · one row per holding: name, shares, value, gain, action, one-line why, needs attention, changed on | My portfolio |
| MarketBrief | Headline · indices · 3 reasons with citations · sector moves · "For you" (text and affected stocks) · Worth a look ×5 (tag, move, why, could be good, could be bad) · watchlist rows (action, what it's waiting for, turned Buy) | Market and Watchlist |
| AlertEvent | Stock, kind, old → new, reason, suggested move, sources, link | Telegram |
| SystemStatus | Each source's health and last refresh time | Status line |

**One rule for this boundary:** read models arrive fully formatted, with ₹ crore values, month-named quarters and plain labels already in place. The UI does no calculation at all, so the same logic can later serve a phone app or the client version unchanged.

## Order for working out the logic

1. **Read models:** lock the contract first and work backwards from what the screens need.
2. **Metric engine and sector templates.**
3. **Signal scoring and red flags.**
4. **Decision rules and stickiness:** the real "brain".
5. **News pipeline:** matching, merging, labelling.
6. **Evidence pack and validator.**
7. **Orchestrator triggers.**
8. **The AI prompts**, last.
