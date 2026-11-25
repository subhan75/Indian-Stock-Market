# Stock Analyst (India) — v0

Type an NSE stock and get a plain-words report: five traffic-light questions, an overall label
(Looks solid / Mixed / Be careful), what the company does, recent news, and a source link for every
number. It explains; it does not give buy or sell advice. *Research aid, not financial advice.*

Design: [Documents/Architecture/V0_Description.md](Documents/Architecture/V0_Description.md).

## Run it

```powershell
python -m venv venv                       # once
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

Open http://127.0.0.1:8000. The first search downloads the NSE company list (about 2,600 stocks).

### AI text (optional)

Copy `.env.example` to `.env` and fill in `OPENAI_API_KEY`, `LABELLER_MODEL` (small, cheap) and
`WRITER_MODEL` (stronger). Without them everything still works, but the news question is grey and the
written summary is replaced by "isn't available right now". `.env` is git-ignored.

## Tests

```powershell
venv\Scripts\python.exe -m pytest backend/tests
```

All network access and the AI are faked in tests; Screener pages are trimmed real fixtures.

## My stocks (Phase 2)

Open `/holdings.html`. Add what you own (shares and average buy price) or just watch a stock. Each row shows
today's value, gain or loss, the stock's label and a **Look at this** tag when one of these is true:
the label is Be careful, the label got worse since the previous report, the price is 20% or more below what
you paid, or new serious news appeared since the previous report. The tag says *why*, never what to do.

- **Refresh all** rebuilds every report one at a time (about 5 seconds each). If Screener.in can't be reached
  for a stock, its earlier report is kept and it is listed as failed.
- Opening the page never calls Screener; it uses cached reports and fetches only live prices.
- Totals leave out any stock whose price couldn't be fetched and say so.
- Contracts, rules and exit criteria: [Documents/Architecture/V0_Phase2_Phase3_Spec.md](Documents/Architecture/V0_Phase2_Phase3_Spec.md).
- AI problems are logged by the server (with API-key fragments removed), so a silent "summary isn't available"
  can be diagnosed from the terminal running uvicorn.

## Market today (Phase 3)

Open `/market.html`: Nifty 50 and Sensex (Yahoo Finance), up to 3 short points on what happened, the 10 newest
market headlines (ET Markets and Business Standard, last 24 hours), which of your stocks are in the headlines,
and the stocks you are watching.

- The points are written by AI from exactly the headlines shown, and each sentence ends with a chip that opens
  the headline it comes from. Text that cites a missing headline, invents a number or uses buy/sell/target/
  recommend is rejected; if nothing passes, the page shows the headlines without points.
- The market part is cached for 15 minutes (the Refresh button bypasses it). Your stocks and Watching are always
  recomputed, so adding a stock shows up immediately.
- "Your stocks in the news" matches headline **titles** against the company name or the all-caps ticker. It does
  not know aliases (SBI, HUL), so those are missed in v0.
- After the close and at weekends the index cards show the last session.
- If a source fails, only its block says so, and the footer names it and when it last worked.

## Tuning

Thresholds for the five questions are in [backend/app/config.py](backend/app/config.py). Change them after
you have read reports for stocks you know (that is part of the plan).

## How a report is built

`GET /api/reports/{symbol}` (cached 24h, `?refresh=true` to skip the cache):

1. Fetch Screener.in, price (Yahoo Finance, Screener as fallback) and Google News in parallel.
2. AI labels the headlines (about the company? good/bad? serious?). Code turns that into question 5.
3. Code scores questions 1–4 and picks the overall label. The AI never decides these.
4. AI writes "Overall" and "What the company does" from numbered facts. A checker rejects text that has
   an uncited sentence, an unknown citation, an invented number, or the words buy/sell/target/recommend;
   on failure the report shows facts only.
5. If any source fails, only its question goes grey and the footer says when it last worked.

### How My stocks is built (Phase 2)

`GET /api/holdings` (opening the page):

1. Read your saved holdings and, for each, its two newest stored reports. This reads cached reports only and
   **never calls Screener**, so the page opens fast.
2. Fetch today's price for every stock in parallel from Yahoo Finance. If that fails, use the price in the stock's
   last report; if there is none, the stock is left out of the totals and a note says so.
3. Code works out value (shares × price), gain or loss (in ₹ and %) and the totals. The AI is not involved.
4. Code applies the four "Look at this" rules by comparing the latest report with the previous one: label is
   Be careful; label got worse; price 20% or more below what you paid; new serious news. A label that drops only
   because a question went grey (a data outage) is not counted as "worse". The flag text is fixed wording and
   never advice.
5. Rows are ordered flagged first, then by value, then watching stocks A to Z.

`POST /api/holdings` and `PUT /api/holdings/{symbol}` (add and edit): validate the input with plain-sentence errors,
save, then build the stock's first report as a best effort (a report failure never blocks the save). Switching a
stock to "watching" clears its shares and buy price.

`POST /api/refresh-all` (the Refresh all button):

1. Record each stock's flags from its stored reports **before** anything changes.
2. Rebuild every report one at a time (Screener's 3-second gap keeps it polite, about 5 seconds per stock).
3. If Screener.in can't be reached for a stock, keep its earlier report and list it under `failed`. A failed news,
   price or AI fetch still saves, with only that question grey.
4. Compare flags before and after: a stock whose flag gained a reason is listed under `new_flags`.
5. Only one refresh runs at a time; a second request is told to try again in a minute.

### How Market today is built (Phase 3)

`GET /api/market/today`:

1. Fetch Nifty 50 and Sensex (Yahoo Finance) and the ET Markets and Business Standard feeds in parallel.
2. Keep the last 24 hours, strip HTML from descriptions, sort newest first and drop the same story seen twice. The
   10 newest are the headlines shown (`H1`…`H10`).
3. AI writes up to 3 short points from exactly those 10 headlines and the index figures. The same kind of checker
   as the report rejects a point that cites a headline that isn't on the page, leaves a sentence uncited, invents a
   number or uses buy/sell/target/recommend. A failing point is dropped; if none pass, the page shows headlines only.
4. This market part is cached for 15 minutes (`?refresh=true` skips it). A page where every source failed is not
   cached, so the next load retries.
5. On every request, whether cached or not: code matches your saved stocks against the **titles of all headlines
   from the last 24 hours** (not just the 10 shown) for "Your stocks in the news", and lists the stocks you marked as
   watching with their latest label.
6. If a source fails, only its block says so, and the footer names it and when it last worked.

More detail and worked examples: [Documents/Testing/Testing_Guide.md](Documents/Testing/Testing_Guide.md).

## Notes from building against live pages

- Screener's peers table is inline in the company page (no separate request). Its P/E column is found by
  header text because banks and telecoms have different columns. Our median excludes the company itself.
- Screener leaves P/E blank only for loss-making companies; that is how question 4 detects a loss.
- Only 8 trusted outlets are kept for news (per the plan), so small and mid caps often have 0–2 headlines.
