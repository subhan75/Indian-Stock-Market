# Phase 2 and 3: Contracts, Rules and Exit Criteria (v0)

Status: **DRAFT for review. No Phase 2 or 3 code is written until this is approved.**
Extends [V0_Description.md](V0_Description.md). Where the two disagree, this file wins for Phases 2 and 3, and every difference is listed in section 3.1 so nothing is hidden.

---

## 1. Decisions to confirm (veto any of these)

| # | Decision | Why |
|---|---|---|
| D1 | The holdings list is ordered: flagged holdings first, then by current value (largest first), then watching stocks A to Z. | The "look at this" rows are what you open the page for. |
| D2 | A stock is flagged by comparing its **latest two stored reports**. A report opened after 24 hours counts as a refresh, same as the Refresh button. | There is no other "refresh" event in a no-background-jobs design. |
| D3 | **Refresh all** never replaces a good report with a Screener-less one. If Screener.in can't be reached for a stock, that stock goes in `failed` and its previous report is kept. News, price or AI failures still save (their questions go grey). | Otherwise one bad fetch would wipe a stock's numbers and trigger false flags. |
| D4 | "Label got worse" is ignored when a question newly went grey (data outage), because greys don't count and can lower the label by themselves. | An OpenAI hiccup must not flag every stock. |
| D5 | `new_flags` and Telegram alerts use **report-derived** reasons only (label, label change, serious news, price from the report). The live price is used for display and the on-screen flag. | Makes them deterministic and testable. |
| D6 | "Your stocks in the news" matches **titles only**, against **all** headlines from the last 24 hours (not just the 10 shown), max 3 headlines per stock, max 10 rows. | A stock's news often isn't in the top 10. |
| D7 | Aliases (SBI for State Bank of India, M&M, HUL) are **not** matched in v0. Known limitation. | Needs an alias table; belongs in a later version. |
| D8 | The Market page shows the **last session** after hours and on weekends. It does not label the session. | yfinance's quick data has no reliable session timestamp. |
| D9 | The market part of the page (indices, points, headlines) is cached for **15 minutes**. Your stocks and Watching are always computed fresh. | Avoids a paid AI call on every reload. |
| D10 | Up to **100** holdings (watching stocks included). | A sane guard, far above real use. |
| D11 | Shares are **whole numbers**. Buy price has up to 2 decimals. | Matches how Indian equity is held; fractional shares can come later. |
| D12 | The Phase 3 AI writer sees exactly the 10 headlines shown on the page. | Every cited headline is visible to the reader. |
| D13 | Telegram alerts and the daily scheduled refresh are **optional** (step 2.6) with their own exit criteria. Core exit does not depend on them. | The doc says "only if the rest works". |

---

## 2. Conventions (apply to every endpoint)

- **Base:** all endpoints under `/api`, JSON only, UTF-8.
- **Errors:** always `{"error": {"code": "bad_request" | "not_found" | "source_unavailable", "message": "plain sentence"}}`. HTTP status: `bad_request` 400, `not_found` 404, `source_unavailable` 503. Malformed JSON or wrong types: 400 `"That request wasn't valid."`.
- **Display strings:** the backend sends ready-to-show text; the frontend does no maths, no rounding, no date formatting.
- **Time:** all clock times are India time (IST). `"3:30 pm"`, `"25 Nov, 3:30 pm"`, `"25 Nov"`. Lower-case am/pm, no leading zero on the hour.
- **Money:** Indian grouping (`₹4,20,000`). Whole rupees for values and gains; a price shows decimals only if it has them (`₹7,028`, `₹7,028.50`). Percentages one decimal (`+15.8%`).
- **Signed values:** `+₹66,300 (+15.8%)`, `-₹5,000 (-3.2%)`, zero is `₹0 (0.0%)`.
- **Direction:** `"up"`, `"down"`, `"flat"` (or `null` where there is nothing to show).
- **Symbols:** upper-case on the way in, stored and returned upper-case. Pattern `^[A-Za-z0-9&\-]{1,20}$`.
- **Links:** only `http`/`https`. The frontend refuses any other scheme.
- **No advice:** no user-visible string produced by Phase 2 or 3 code contains buy, sell, target or recommend (flag text, Telegram text and AI text are all checked).

---

## 3. Data and configuration changes

### 3.1 Changes to existing contracts (all additive)

| Where | Change | Reason |
|---|---|---|
| Report `price` | add `value`: number or `null` | Holdings maths and the "20% below" rule need a number. Missing on reports cached before this change, which are treated as unknown. |
| Report `news[]` | add `serious`: boolean | The "serious news appeared" rule. |
| MarketToday `your_stocks_in_news[]` | add `name`, `title`, `outlet`, `url`, `time_display`, `report_url`; `headline_id` may be `null` | A match may not be in the top 10 headlines. |
| MarketToday | add `sources[]`, `disclaimer` | Same footer behaviour as the report. |
| Holdings `totals` | add `note`, `excluded` | Honest totals when a price is missing. |
| Holdings `flag` | add `reasons[]` | The UI can show each reason; `reason` stays as the joined text. |
| Holdings `rows[]` | add `price_display`, `price_source`, `has_report`, `report_url`, `buy_price` | Row needs the current price and a link. |
| `POST/PUT` | "saved row" is defined as the stored record (section 4.2) | The doc left it open. |

### 3.2 Database (existing file, `CREATE TABLE IF NOT EXISTS`, so no migration step)

```sql
CREATE TABLE IF NOT EXISTS holdings (
  symbol    TEXT PRIMARY KEY,
  shares    INTEGER,
  buy_price REAL,
  watching  INTEGER NOT NULL DEFAULT 0 CHECK (watching IN (0, 1)),
  added_at  TEXT NOT NULL,                      -- ISO 8601 with +05:30
  CHECK (watching = 1 OR (shares IS NOT NULL AND buy_price IS NOT NULL AND shares > 0 AND buy_price > 0))
  -- the IS NOT NULL parts matter: SQLite treats a NULL CHECK result as a pass
);
CREATE TABLE IF NOT EXISTS flags_sent (
  symbol  TEXT NOT NULL,
  reason  TEXT NOT NULL,                        -- comma-joined reason codes, e.g. "be_careful,price_drop"
  sent_at TEXT NOT NULL                         -- ISO 8601
);
CREATE INDEX IF NOT EXISTS idx_flags_sent ON flags_sent (symbol, sent_at);
```
The market cache reuses `page_cache` with `url = 'market:today'`. No other table changes.

### 3.3 Configuration (`config.py`)

| Constant | Value |
|---|---|
| `FLAG_PRICE_DROP_PCT` | 20 |
| `MAX_HOLDINGS` | 100 |
| `MAX_SHARES` | 10,000,000 |
| `MAX_BUY_PRICE` | 10,000,000 |
| `MARKET_CACHE_MINUTES` | 15 |
| `MARKET_WINDOW_HOURS` | 24 |
| `MARKET_HEADLINES_SHOWN` | 10 |
| `MARKET_POINTS_MAX` | 3 |
| `MATCH_MAX_PER_STOCK` / `MATCH_MAX_TOTAL` | 3 / 10 |
| `TELEGRAM_COOLDOWN_HOURS` | 24 |

New names in `.env.example` (values are never read by me): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `APP_BASE_URL` (default `http://127.0.0.1:8000`). `WRITER_MODEL` is reused for the market writer.

---

## 4. Phase 2 contracts: My stocks

### 4.1 Endpoints

| Method and path | Body or query | Success | Notes |
|---|---|---|---|
| `GET /api/holdings` | none | 200 `Holdings` | Reads cached reports only; fetches live prices in parallel; never calls Screener. |
| `POST /api/holdings` | `HoldingIn` | 201 `HoldingSaved` | Builds the stock's report best-effort after saving; a report failure never fails the save. |
| `PUT /api/holdings/{symbol}` | `HoldingIn` | 200 `HoldingSaved` | Path symbol is authoritative. |
| `DELETE /api/holdings/{symbol}` | none | 200 `{"deleted": true}` | Reports are kept. |
| `POST /api/refresh-all` | none | 200 `RefreshResult` | Section 4.5. |

### 4.2 Schemas

**HoldingIn**
```json
{"symbol": "BAJFINANCE", "shares": 50, "buy_price": 720.5, "watching": false}
```
| Field | Type | Rule |
|---|---|---|
| `symbol` | string | required, matches the symbol pattern, must be in the NSE list |
| `watching` | boolean | optional, default `false` |
| `shares` | integer | required when `watching` is false: 1 to `MAX_SHARES`. Strings and decimals are rejected. If `watching` is true it is ignored and stored as null. |
| `buy_price` | number | required when `watching` is false: more than 0, up to `MAX_BUY_PRICE`, rounded to 2 decimals. Ignored when watching. |

**HoldingSaved**
```json
{"symbol": "BAJFINANCE", "name": "Bajaj Finance Limited", "watching": false,
 "shares": 50, "buy_price": 720.5, "added_at": "2026-11-25T10:15:00+05:30"}
```

**Holdings (GET)**
```json
{
  "as_of": "25 Nov, 3:30 pm",
  "totals": {
    "invested_display": "₹4,20,000", "value_display": "₹4,86,300",
    "gain_display": "+₹66,300 (+15.8%)", "direction": "up",
    "excluded": 1, "note": "1 stock isn't included because its price couldn't be fetched."
  },
  "rows": [
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance Limited", "watching": false,
     "shares": 50, "buy_price": 720.5, "buy_price_display": "₹720.50",
     "price_display": "₹920", "price_source": "live",
     "value_display": "₹46,000", "gain_display": "+₹9,975 (+27.7%)", "direction": "up",
     "has_report": true, "label": {"code": "mixed", "display": "Mixed"},
     "flag": {"on": true,
              "reasons": [{"code": "label_worse", "text": "Label went from Looks solid to Mixed"}],
              "reason": "Label went from Looks solid to Mixed"},
     "report_updated_display": "25 Nov", "report_url": "/report.html?symbol=BAJFINANCE"}
  ]
}
```
Field rules:
- `price_source`: `"live"` (Yahoo Finance), `"report"` (last report's `price.value`) or `null`. When `null`, `price_display` is `"Price unavailable"` and `value_display`, `gain_display`, `direction` are `null`.
- Watching rows: `shares`, `buy_price`, `buy_price_display`, `value_display`, `gain_display`, `direction` are `null`; `price_display` is still filled.
- No report yet: `has_report: false`, `label: null`, `report_updated_display: null`, `flag.on: false`, `flag.reasons: []`, `flag.reason: ""`.
- `totals` is computed over holdings that have a price. `excluded` counts holdings without one; `note` is `null` when `excluded` is 0. Watching rows are never in totals. With no priced holdings every `*_display` in totals is `"₹0"` (gain `"₹0 (0.0%)"`), `direction` `"flat"`.
- `direction` is `flat` when gain rounds to 0.0%.

### 4.3 Validation and error catalogue (exact messages)

| Condition | Status, code | Message |
|---|---|---|
| Symbol fails the pattern | 400 `bad_request` | `That doesn't look like an NSE symbol.` |
| Symbol not in the NSE list | 404 `not_found` | `{SYM} isn't on the NSE equity list. Check the symbol or search by company name.` |
| `shares` missing, not an integer, or below 1 | 400 `bad_request` | `Enter the number of shares as a whole number, 1 or more.` |
| `shares` above `MAX_SHARES` | 400 `bad_request` | `That number of shares looks too large. Check it.` |
| `buy_price` missing, not a number, 0 or negative, or above the max | 400 `bad_request` | `Enter your average buy price in rupees, more than 0.` |
| POST for a symbol already saved | 400 `bad_request` | `You already have {SYM}. Edit it instead.` |
| More than `MAX_HOLDINGS` | 400 `bad_request` | `You can keep up to 100 stocks in v0.` |
| PUT body symbol differs from the path symbol | 400 `bad_request` | `The symbol in the form doesn't match the stock being edited.` |
| PUT or DELETE for a symbol not saved | 404 `not_found` | `{SYM} isn't in your stocks.` |
| NSE list unavailable and empty | 503 `source_unavailable` | `Couldn't fetch the NSE company list: {reason}` |

Switching a holding to watching (PUT with `watching: true`) clears its shares and buy price. The UI asks for confirmation first.

### 4.4 The "Look at this" flag (exact semantics)

Inputs: the holding, the current price, the **latest** stored report (L) and the **previous** stored report (P, the second newest for that symbol; may not exist).

| Code | Applies to | Fires when | Text |
|---|---|---|---|
| `be_careful` | holdings and watching | L.label is `be_careful` | `Label is Be careful` |
| `label_worse` | holdings and watching | P exists, rank(L.label) < rank(P.label) with rank looks_solid 3, mixed 2, be_careful 1, **and** no question is grey in L that was not grey in P (D4) | `Label went from {Old} to {New}` |
| `price_drop` | holdings only | current price is known and `round((buy - price) / buy * 100, 2) >= 20` | `Price is {n}% below your buy price` where n is that percentage rounded down to a whole number |
| `serious_news` | holdings and watching | P exists, P's Google News source was ok, and L has at least one `news[]` item with `serious: true` whose URL is not in P's news URLs | `New serious news since the last refresh` |

- `flag.on` is true when at least one rule fires. `reasons` lists them in the table's order. `reason` is the texts joined with `"; "`.
- Reports lacking `news[].serious` or `price.value` (cached before Phase 2) never fire the rules that need them.
- Flag text is never an instruction. All four texts are fixed strings above, so they cannot contain advice wording.
- "Current price" for `price_drop` on screen is the row's price (live, else report). For `new_flags` and alerts it is the report's `price.value` (D5).

### 4.5 `POST /api/refresh-all`

**Response**
```json
{"refreshed": ["ABB", "TITAN"],
 "failed": [{"symbol": "INFY", "reason": "Screener.in couldn't be reached, so the earlier report was kept."}],
 "new_flags": ["TITAN"]}
```
Behaviour:
1. Takes every saved stock (holdings and watching) in `added_at` order. Zero stocks gives `{"refreshed": [], "failed": [], "new_flags": []}` with status 200.
2. Before touching anything, computes each stock's report-derived flag codes (D5).
3. For each stock, one at a time, builds a fresh report. If Screener.in could not be reached, the stock goes to `failed` and nothing is saved (D3). Any other degraded source still saves.
4. Recomputes flag codes. A stock is in `new_flags` when it has a code now that it did not have before.
5. One stock failing never stops the others.
6. Only one refresh runs at a time. A second call while one is running gets 400 `bad_request`: `A refresh is already running. Try again in a minute.`
7. Typical time is 4 to 8 seconds per stock (Screener's 3-second gap plus other fetches). There is no server timeout; the UI says so.
8. If Telegram is configured, alerts go out for `new_flags` (section 4.6) after the loop. Alert failures never affect this response.

`failed[].reason` is the plain message of the error, or `Something unexpected went wrong.`.

### 4.6 Optional alert (step 2.6)

- Sent only for `new_flags` stocks, only if `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set.
- Text: `{Name} ({SYM}): {reason}. Report: {APP_BASE_URL}/report.html?symbol={SYM}`.
- At most one message per symbol per rolling 24 hours (`flags_sent`), whatever the reason. `flags_sent.reason` stores the comma-joined codes.
- 10-second timeout; failures are logged with no token or chat id in the log line and are otherwise ignored.
- Daily run (if wanted): `python -m backend.cli refresh_all`, scheduled by Windows Task Scheduler. Nothing is scheduled inside the app.

---

## 5. Phase 3 contracts: Market today

### 5.1 Endpoint

`GET /api/market/today?refresh=false` returns 200 `MarketToday`. `refresh=true` bypasses the 15-minute cache. It only returns an error for an invalid `refresh` value (400). Source failures degrade the page instead.

### 5.2 Schema

```json
{
  "as_of": "25 Nov, 7:19 pm",
  "indices": [
    {"name": "Nifty 50", "value_display": "25,819", "change_display": "+1.8%", "direction": "up",
     "source": "Yahoo Finance", "url": "https://finance.yahoo.com/quote/%5ENSEI/"},
    {"name": "Sensex", "value_display": "83,938", "change_display": "+1.8%", "direction": "up",
     "source": "Yahoo Finance", "url": "https://finance.yahoo.com/quote/%5EBSESN/"}
  ],
  "points": [{"text": "Both indices rose about 1.8% [H2].", "cites": ["H2"]}],
  "headlines": [
    {"id": "H1", "title": "...", "outlet": "ET Markets", "time_display": "7:19 pm", "url": "https://..."}
  ],
  "your_stocks_in_news": [
    {"symbol": "ABB", "name": "ABB India Limited", "headline_id": "H3", "title": "...",
     "outlet": "Business Standard", "time_display": "5:49 pm", "url": "https://...",
     "report_url": "/report.html?symbol=ABB"}
  ],
  "watching": [
    {"symbol": "TITAN", "name": "Titan Company Limited",
     "label": {"code": "looks_solid", "display": "Looks solid"}, "report_url": "/report.html?symbol=TITAN"}
  ],
  "sources": [{"name": "Yahoo Finance", "ok": true, "fetched_at_display": "25 Nov, 7:19 pm"},
              {"name": "ET Markets", "ok": true, "fetched_at_display": "25 Nov, 7:19 pm"},
              {"name": "Business Standard", "ok": true, "fetched_at_display": "25 Nov, 7:19 pm"}],
  "ai_text": true,
  "disclaimer": "Research aid, not financial advice."
}
```
Field rules:
- `indices`: Nifty 50 first, then Sensex. An index that couldn't be fetched is omitted and its source row says `ok: false`. Both failing gives `[]`. Change is vs the previous close.
- `headlines`: up to 10, newest first. IDs are `H1` to `H10` in display order. `time_display` is `"2:10 pm"` for today (IST) and `"24 Nov, 9:05 pm"` for earlier. Each outlet is exactly `ET Markets` or `Business Standard`.
- `points`: 0 to 3. Every point's text ends each sentence with `[H#]` markers, and `cites` equals the set of markers used. `ai_text` is true only if at least one point passed the check. With no headlines, no AI configured, or two failed attempts, `points` is `[]` and `ai_text` is false.
- `your_stocks_in_news`: one row per (stock, headline) match, newest first, at most 3 per stock and 10 total. `headline_id` is the matching `H#` if that headline is in the top 10, else `null`.
- `watching`: stocks saved with `watching: true`, A to Z, `label` from the latest stored report or `null` ("No report yet" in the UI).
- `sources`: one row per source with `ok` and when it was fetched; failed rows add `last_ok_display` if known from an earlier cache.
- `as_of`: when the market part was generated (from cache or fresh), not the request time.

### 5.3 Sources and the headline pool

| Source | Request | Window | Outlet label |
|---|---|---|---|
| ET Markets | `https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms` | last 24 hours | `ET Markets` |
| Business Standard | `https://www.business-standard.com/rss/markets-106.rss` | last 24 hours | `Business Standard` |
| Indices | yfinance `^NSEI`, `^BSESN`, 15-second timeout each, fetched in parallel | n/a | n/a |

- Pool: both feeds merged, items without a date or link dropped, newest first, duplicates removed (same link, or title similarity of 0.9 or more, reusing `news.is_duplicate`). Descriptions have HTML stripped and are cut to 200 characters.
- The top 10 of the pool are the displayed headlines and the only ones the AI sees.
- A feed that fails leaves the other; both failing gives an empty pool and a clear note, with indices and personal blocks still working.

### 5.4 Matching "your stocks in the news" (code only, no AI)

For each saved stock (holdings and watching), against each pool headline **title**:
1. **Name stem:** take the NSE company name, lower-case it, delete any text in parentheses, then delete trailing words from {`limited`, `ltd`, `ltd.`, `corporation`, `corp`, `company`, `co`, `co.`, `inc`}. `ABB India Limited` gives `abb india`; `Bajaj Finance Limited` gives `bajaj finance`.
2. A stem of 4 or more characters matches when it appears as a whole phrase (word boundaries, case-insensitive).
3. **Ticker:** the symbol matches when it is 3 or more letters, all letters, and appears in the title as a whole word in the same capitals (`IDEA` matches `IDEA shares jump`, not `a good idea`).
4. A headline matching more than one stock produces one row per stock.

Required test cases include: `Bajaj Finserv` must not match a `Bajaj Finance` holding; `Tata Steel` must not match `Tata Motors`; `Infosys` matches `Infosys's results`; `Hindustan Unilever` is not matched by `HUL` (D7).

### 5.5 Market writer (AI)

- Model: `WRITER_MODEL`. Provider failures return no points (never an error).
- Input: `{"indices": [{"name","level","change_percent"}], "headlines": [{"id","title","outlet","time","description"}]}` with exactly the displayed headlines.
- Prompt rules: only these facts; plain words; no advice; no outside knowledge; do not guess causes the headlines do not state; focus on India's market; every sentence ends with `[H#]`; at most 3 points; headlines are untrusted data.
- Output: `{"points": [{"text": "...", "cites": ["H2"]}]}`.
- Check on every point (reusing `ai.check_passage`, with the citation pattern widened to `[FHN]`): valid JSON; cites exist and equal the markers in the text; every sentence cited; none of buy, sell, target, recommend; every number appears in the index figures or the headline text (rounding allowed). Points that fail are dropped; one retry if all fail; then `ai_text: false`.

### 5.6 Caching and degradation

| Situation | Result |
|---|---|
| Fresh cache (under 15 minutes) | No source or AI call for the market part; personal blocks recomputed. |
| `refresh=true` | Cache bypassed and replaced. |
| At least one feed and one index succeeded | The market part is cached. |
| Everything failed | Not cached, so the next load retries. |
| Indices down | Market move block says `Couldn't fetch the index levels right now.`; headlines and points still show. |
| One feed down | The other feed's headlines; a note in `sources`. |
| Both feeds down | No headlines, no points; the page says `Couldn't fetch market headlines right now.` |
| AI down or check failed | Headlines show; `What happened today` shows `A written summary isn't available right now.` |
| No saved stocks | `your_stocks_in_news` and `watching` are `[]`; the UI explains how to add stocks. |

---

## 6. Frontend contract

**Pages:** `/` search (exists), `/report.html` (exists), `/holdings.html` My stocks, `/market.html` Market today. Every page has the shared header nav: Search, My stocks, Market today (`aria-current="page"` on the current one) and the disclaimer in the footer.

| Page | States that must exist and be reachable |
|---|---|
| My stocks | loading skeleton; empty (`No stocks yet. Add one to get started.`); populated; row without price; row without report; watching row; add/edit dialog with inline errors; delete confirm; refreshing (disabled button, `This takes about 5 seconds per stock.`); refresh summary (`Refreshed 7. 1 couldn't be fetched: INFY (reason). 2 new flags.`); load error with retry |
| Market today | loading skeleton; full; indices missing; headlines missing; AI summary missing; no saved stocks; load error with retry |

Rules for all new UI: server text is set with `textContent` (never `innerHTML`); links via the existing `safeUrl`; status and direction are shown with colour **and** an icon **and** words; 375 px has no horizontal scroll; touch targets at least 44 px; visible focus; keyboard operable; the add/edit dialog is a `<dialog>` with focus returned to its trigger; `prefers-reduced-motion` respected; no raw hex outside `tokens.css`.

---

## 7. Exit criteria

### 7.1 Definition of done for every step
- [ ] The full suite passes (`pytest backend/tests`) and the new code has its own tests.
- [ ] No test makes a real network call or calls a real AI.
- [ ] Committed with a clear message; `git status` shows only `test.py` and `test.md` untracked.
- [ ] README or this spec updated if behaviour changed.
- [ ] No secret in code, tests, logs or commits.

### 7.2 Phase 2 exit (all must be true)

| # | Criterion | How it is checked | Who |
|---|---|---|---|
| E2.1 | `GET/POST/PUT/DELETE /api/holdings` and `/api/refresh-all` return exactly the schemas and error messages in section 4, for every row of the error catalogue. | Automated endpoint tests, one per catalogue row and per schema. | Auto |
| E2.2 | Flag rules behave exactly as 4.4: each rule has a firing test and a not-firing test, including the exact 20% boundary, the outage guard (D4), a missing previous report, an old report lacking new fields, and the unseen-serious-URL rule. | Automated, fixed inputs. | Auto |
| E2.3 | Holdings maths matches hand-computed values for at least 6 cases (gain, loss, flat, price missing, watching, mixed list), including Indian grouping and totals. | Automated. | Auto |
| E2.4 | `refresh-all`: partial failure, keeps the old report when Screener fails (D3), correct `new_flags` before and after, empty list, concurrent call rejected. | Automated with fakes. | Auto |
| E2.5 | `GET /api/holdings` never calls Screener, and opening My stocks with 20 holdings takes under 5 seconds typical, never more than 20 seconds (price timeouts bound it). | Automated assertion on the Screener fake; timed once with live data. | Auto + you |
| E2.6 | You have entered every stock you own, and **each row's value and the total agree with your broker within 0.5%** when compared at the same time. | Side-by-side check. | You |
| E2.7 | Every row opens the right report. | Click every row. | You |
| E2.8 | Flags fire for the right reasons on live data: a buy price at least 25% above today's price triggers `price_drop`; a weak stock such as IDEA shows `be_careful`; a strong stock with a lower buy price shows no flag. | Manual test with a throwaway database. | You |
| E2.9 | No false flags on first load: with exactly one report per stock, no `label_worse` and no `serious_news` flag appears. | Automated plus manual. | Auto + you |
| E2.10 | Browser pass at desktop and 375 px: add, edit, switch to watching, delete, Refresh all, every state in section 6, no console errors, no horizontal scroll, keyboard-only use of the dialog. | Playwright script plus screenshots read by eye. | Auto + me |
| E2.11 | Security and robustness: oversized, negative, string and decimal inputs rejected with the right message; no script injection through names or reasons; the API never echoes secrets. | Automated. | Auto |
| E2.12 | Suite green, committed, README documents the holdings page and refresh behaviour. | Command output. | Auto |

**Optional Telegram exit (only if built):** E2.T1 with token unset the app behaves identically and logs nothing sensitive; E2.T2 a real message arrives once with a working link; E2.T3 a second refresh within 24 hours sends nothing for the same stock; E2.T4 a failing Telegram call does not change the refresh response (automated with a fake).

### 7.3 Phase 3 exit (all must be true)

| # | Criterion | How it is checked | Who |
|---|---|---|---|
| E3.1 | `GET /api/market/today` returns exactly the schema in 5.2 for the full case and for each row of the degradation table in 5.6. | Automated matrix. | Auto |
| E3.2 | Feed parsing: real saved ET and Business Standard fixtures give correct titles, IST times, window filtering, HTML-free descriptions, cross-feed de-duplication, and survive an item with no date. | Automated on fixtures. | Auto |
| E3.3 | The market writer is rejected, then retried once, for every bad case: invalid JSON, unknown cite, uncited sentence, banned word, invented number, more than 3 points. A clean response passes. | Automated with a fake LLM. | Auto |
| E3.4 | Matching passes a fixed test set of at least 10 true matches and 10 look-alike non-matches with **no errors**, including every case named in 5.4. | Automated. | Auto |
| E3.5 | Caching: a second request within 15 minutes makes **zero** source and AI calls for the market part; `refresh=true` makes them; a total failure is not cached. | Automated call counters. | Auto |
| E3.6 | The page loads with today's numbers: Nifty and Sensex levels within 0.1% of a live reference at the same moment, and 10 headlines newest first. Cold load under 20 seconds, warm under 2 seconds. | Manual comparison plus timing. | You |
| E3.7 | Every point links to a real headline that says it: you read the cited headline for each of at least 3 points on at least 2 different days, and none overstates it. | Manual spot-check. | You |
| E3.8 | Your stocks in the news shows a stock you own on a day it is in the headlines, checked by hand on at least 3 different days, with no wrong matches seen. | Manual. | You |
| E3.9 | Watching lists every stock you marked watching, with its label and a working link. | Manual. | You |
| E3.10 | Browser pass at desktop and 375 px for every state in section 6: no console errors, no horizontal scroll, links open safely. | Playwright plus screenshots. | Auto + me |
| E3.11 | Suite green, committed, README documents the Market page and its cache. | Command output. | Auto |

### 7.4 Gates
- **Start Phase 2:** this spec approved. Using Phase 1 for a week on stocks you know (the v0 doc's advice) is recommended but is your call.
- **Start Phase 3:** E2.1 to E2.5 and E2.9 to E2.12 are met (the manual ones, E2.6 to E2.8, can follow but should happen before relying on Phase 3's "your stocks").
- **Phase 2 is "done":** every row of 7.2 is ticked. **Phase 3 is "done":** every row of 7.3 is ticked. Rows marked "You" are not tickable by me; I will list exactly what I need you to check.

---

## 8. Out of scope for Phases 2 and 3
Buy/sell advice; tax lots and buy dates; sector or fund-flow data; alias matching; per-stock news pages; charts; multi-user or login; exports; background refresh inside the app; fractional shares; currency other than INR; editing a report's thresholds from the UI.

## 9. Known risks
- Google News rate limits (HTTP 429) under heavy Refresh all use: handled as a failed source, but a large portfolio could see many grey news questions. Mitigation: the existing 3-second Screener gap also spaces runs; consider a small gap between news fetches if this shows up in use.
- yfinance is unofficial and can change or fail; the Screener price fallback and `price_source` make this visible.
- Screener's page layout can change; saved fixtures catch parser regressions in tests but not live changes.
- Title-only matching will miss headlines that name a stock only by alias or in the body (D7).
