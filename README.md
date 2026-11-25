# Stock Analyst (India) — v0, Phase 1: Stock report

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
