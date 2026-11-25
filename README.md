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

## Notes from building against live pages

- Screener's peers table is inline in the company page (no separate request). Its P/E column is found by
  header text because banks and telecoms have different columns. Our median excludes the company itself.
- Screener leaves P/E blank only for loss-making companies; that is how question 4 detects a loss.
- Only 8 trusted outlets are kept for news (per the plan), so small and mid caps often have 0–2 headlines.
