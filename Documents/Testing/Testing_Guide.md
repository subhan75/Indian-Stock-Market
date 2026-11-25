# Testing Guide: Phases 1, 2 and 3

How to test every function of the Stock Analyst v0, with commands you can paste and the output to expect.
Every example here was run against the real app on 25 Nov 2026; live market numbers (prices, labels, headlines)
change daily, so compare the **shape and wording**, not the exact figures.

Contents: [0 Setup](#0-setup) · [1 The automated suite](#1-the-automated-suite) ·
[2 Phase 1 functions](#2-phase-1-stock-report) · [3 Phase 2 functions](#3-phase-2-my-stocks) ·
[4 Phase 3 functions](#4-phase-3-market-today) · [5 Breaking things on purpose](#5-breaking-things-on-purpose) ·
[6 Exit-criteria checklist](#6-exit-criteria-checklist) · [7 Troubleshooting](#7-troubleshooting)

---

## 0. Setup

Open PowerShell in the project folder. Everything below uses the project's own Python (`venv`).

The app now needs a **signed-in user** for everything except `/api/health`. There are two ways to run it for testing.

### 0.1 Quickest: the fake login and database (no Supabase needed)
`scripts/dev_fake_server.py` runs the real app against an in-memory **fake** Supabase. Nothing real is touched, and
everything you save disappears when you stop it. The data sources (Screener, news, prices, OpenAI) are the real ones.

```powershell
$env:ALLOW_FAKE_SUPABASE = "1"
venv\Scripts\python.exe scripts\dev_fake_server.py 8000
```
It prints two fake accounts. Use `dev@example.com` / `dev-password-123` (and `partner@example.com` /
`partner-password-123` when a test needs a second person). Open <http://127.0.0.1:8000>. Stop it with Ctrl+C.

### 0.2 Against your real Supabase project (use a TEST account, never your real one)
Set `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` and `COOKIE_SECURE=false` as in the README, run
`venv\Scripts\python.exe -m uvicorn backend.app.main:app`, and sign in with an account you created in Supabase for testing.
Reports and holdings are saved to that account, so a separate test account keeps your real data clean.

### 0.3 The PowerShell helper (paste once per window)
It signs in once and then sends the session cookie with every call, decodes UTF-8 (so `₹` shows correctly in Windows
PowerShell 5.1), and prints error bodies. Change `$Base` if you used another port.

```powershell
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Base = "http://127.0.0.1:8000"
$Session = $null
function Login($Email, $Password) {
  $r = Invoke-WebRequest "$Base/api/auth/login" -Method POST -ContentType "application/json" `
        -Body (@{ email = $Email; password = $Password } | ConvertTo-Json -Compress) `
        -Headers @{ Origin = $Base } -SessionVariable s -UseBasicParsing
  $script:Session = $s
  [Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())
}
function Api($Method, $Path, $Body = $null) {
  try {
    $p = @{ Uri = "$Base$Path"; Method = $Method; ContentType = "application/json"; UseBasicParsing = $true; Headers = @{ Origin = $Base } }
    if ($script:Session) { $p.WebSession = $script:Session }
    if ($null -ne $Body) { $p.Body = ($Body | ConvertTo-Json -Compress) }
    $r = Invoke-WebRequest @p
    "HTTP $([int]$r.StatusCode) " + [Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())
  } catch {
    $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "no response" }
    "HTTP $code " + $_.ErrorDetails.Message
  }
}
```
Try it (these outputs were checked):
```powershell
Api GET "/api/holdings"                              # HTTP 401 {"error":{"code":"unauthorized","message":"Please sign in."}}
Login "dev@example.com" "dev-password-123"           # {"user":{"email":"dev@example.com"}}
Api GET "/api/auth/me"                               # HTTP 200 {"user":{"email":"dev@example.com"}}
```
`Api GET "/api/health"` is the only call that needs no login.

### 0.4 How to read a result
Each test has **Do**, **Expect** and (where useful) **Pass if**. Error bodies always look like
`{"error":{"code":"...","message":"..."}}`, and the **message** wording is part of what is tested. Every example below
assumes you ran `Login` first.

---

## 1. The automated suite

703 tests (682 run offline and 21 more only when you provide a real Supabase test project, see the deploy guide). None of
them touch the internet, a real AI, or a real login: sources, Supabase Auth and the database are replaced by fakes (real
network calls are *blocked* in tests), and Screener pages and RSS feeds are saved real samples in `backend/tests/fixtures/`.

```powershell
venv\Scripts\python.exe -m pytest backend/tests -q                  # everything (about 15 seconds)
venv\Scripts\python.exe -m pytest backend/tests/test_flags.py -q    # one file
venv\Scripts\python.exe -m pytest backend/tests -q -k "outage"      # tests whose name contains "outage"
venv\Scripts\python.exe -m pytest backend/tests -q -x               # stop at the first failure
```
**Expect:** a last line like `682 passed, 21 skipped in 14s`. A failure prints the test name, the line, and
`assert <actual> == <expected>`; fix the code or, if the behaviour was deliberately changed, the test and the spec.

| File | Tests | What it proves |
|---|---:|---|
| `test_health.py` | 1 | The app starts and `/api/health` answers |
| `test_search.py`, `test_memcache_nse.py` | 29 | NSE list parsing, search ranking, the bundled fallback list, the in-memory caches |
| `test_screener.py` | 31 | Parsing 7 real pages (normal, bank, loss-maker, blank), 24 h cache, consolidated→standalone fallback |
| `test_scoring.py` | 65 | All five questions at every boundary, lender rule, grey rules, overall label, ₹ formatting |
| `test_news_prices.py` | 31 | Google News trusted-outlet filter, 30-day window, de-duplication; price fallback; IST time |
| `test_ai.py`, `test_ai_logging.py` | 45 | Headline labeller, report writer, citation checker (every rejection), retry once, logs never contain a key |
| `test_report.py` | 21 | Full report contract, cache and refresh, every source-down case |
| `test_holdings_api.py` | 43 | Add/edit/delete holdings, every validation message |
| `test_portfolio.py` | 28 | Value, gain, totals, price fallbacks, ordering, never calls Screener |
| `test_flags.py`, `test_craft_report.py` | 38 | The four "Look at this" rules, boundaries, the outage guard, the test helper |
| `test_refresh.py` | 28 | Refresh all and refresh one: partial failure, keep-old-report, new flags, per-user locks |
| `test_market_sources.py`, `test_market_ai.py`, `test_matching.py`, `test_market_endpoint.py` | 127 | Feeds on real samples, the market writer, name matching (true matches and look-alikes), caching and every degradation |
| `test_store.py`, `test_store_contract.py`, `test_store_supabase.py` | 81 | One contract that the in-memory store **and** the real Supabase client (over a fake server) must both pass, row-level security between two users, error handling, **no secret key anywhere in the repo** |
| `test_auth_provider.py`, `test_auth_routes.py` | 84 | Sign-in, token checks, safe renewal under simultaneous requests, logout of one device, lockout, cookie flags, CSRF, every data route closed without a session, no token in any log |
| `test_deploy_files.py`, `test_frontend_structure.py` | 51 | Strict security headers, the Docker image, pinned dependencies, phone metadata, accessibility structure, no raw colours, no tokens in browser storage |

---

## 2. Phase 1: Stock report

### 2.1 Company list and search
**What it does:** downloads the NSE equity list weekly (EQ and BE series) and searches it by symbol or name.
**Automated:** `test_search.py`.
**Manual:**
```powershell
Api GET "/api/stocks/search?q=abb"
Api GET "/api/stocks/search?q=bajaj"
Api GET "/api/stocks/search?q="
```
**Expect:** first call → `HTTP 200 [{"symbol":"ABB","name":"ABB India Limited"},{"symbol":"ABBOTINDIA",...}]`
(exact symbol first, then prefix, then name). Third call → `HTTP 200 []`. At most 10 results.
**Pass if:** an exact symbol outranks longer names, and an empty query returns an empty list, not an error.

### 2.2 Report: the five questions and overall label
**What it does:** `GET /api/reports/{symbol}` builds (or serves a cached, under-24 h) report.
**Automated:** `test_scoring.py` (rules), `test_report.py` (assembly), `test_screener.py` (parsing).
**Manual:**
```powershell
$r = (Api GET "/api/reports/ABB") -replace '^HTTP 200 ',''
$j = $r | ConvertFrom-Json
"label=$($j.label.display) price=$($j.price.display) ai_text=$($j.ai_text)"
$j.questions | % { "$($_.id): $($_.status) - $($_.value_display)" }
```
**Expect (25 Nov 2026):**
```
label=Looks solid price=₹7,028.50 ai_text=True
growth: green - Sales up 11.7% over the last 4 quarters vs the 4 before
efficiency: green - Return on capital 29.9%, profit margin 15%
debt: green - Borrowings are 0.02× the owners' money (borrowings ₹145 Cr, owners' money ₹9,339 Cr)
price: amber - P/E 94.8 vs 85.8 for similar companies (1.10× theirs)
news: green - Nothing negative in the last 30 days
```
(`ai_text=False` is normal if no OpenAI key is configured; see [7](#7-troubleshooting).)

Thresholds being tested (from `backend/app/config.py`):

| Question | Green | Amber | Red |
|---|---|---|---|
| Growth (sales, last 4 qtrs vs prior 4) | ≥ 10% | 0 to 10% | below 0 |
| Efficiency (ROCE) | ≥ 15% | 10 to 15% | below 10% |
| Debt (borrowings ÷ equity + reserves) | below 0.5 | 0.5 to 1 | above 1 |
| Price (P/E vs median of peers) | ≤ 1.0× | ≤ 1.5× | above 1.5×, or a loss |
| News | none negative | some negative | serious |

Overall label: **Looks solid** = no red and at least 3 green · **Be careful** = 2+ red, or news red · else **Mixed**.
Grey ("no data") questions count for nothing.

**Stocks that exercise special cases** (try each in the browser or with the call above):

| Stock | Why it is useful | Expect |
|---|---|---|
| `HDFCBANK` | A lender | debt row **grey**, "Doesn't apply to lenders…"; label is never "Looks solid" (capped at Mixed) |
| `IDEA` | Loss-making, negative net worth | price **red** ("making a loss"), debt **red** ("owners' money … negative"); label **Be careful** |
| `GILLETTE` | Screener's consolidated page is blank | ROCE and price rows **grey**; report still opens |
| `NOSUCHSTOCK` | Not on the NSE list | `HTTP 404` and the message `NOSUCHSTOCK isn't on the NSE equity list. Check the symbol or search by company name.` |

### 2.3 Cache and refresh
```powershell
Measure-Command { Api GET "/api/reports/ABB" | Out-Null } | % { "first: {0:n1}s" -f $_.TotalSeconds }
Measure-Command { Api GET "/api/reports/ABB" | Out-Null } | % { "second: {0:n2}s" -f $_.TotalSeconds }
Measure-Command { Api GET "/api/reports/ABB?refresh=true" | Out-Null } | % { "refresh: {0:n1}s" -f $_.TotalSeconds }
```
**Expect:** first about 3 to 15 s, second near 0 s (served from the 24 h cache), refresh slow again.
**Pass if:** the second call is dramatically faster and `generated_at` is identical to the first.
`Api GET "/api/reports/ABB?refresh=maybe"` → `HTTP 400` "That request wasn't valid."

### 2.4 Recent reports
`Api GET "/api/reports/recent"` → a list, newest first, one entry per stock:
`[{"symbol":"TITAN","name":"Titan Company Limited","label":"be_careful","generated_at":"2026-11-25T21:18:05+05:30"},...]`
**Pass if:** the literal path `recent` is not treated as a stock symbol.

### 2.5 Price (Yahoo Finance, Screener fallback)
**Automated:** `test_news_prices.py` (`test_price_*`). **Manual:** the report's `price.value` is a number and
`price.change_display` is like `+2.3%`. With the dead-proxy recipe in [5.1](#51-all-outside-sources-down) the price
falls back to Screener's, `change_display` is empty and the footer lists Yahoo Finance as failed.

### 2.6 News (Google News, trusted outlets only)
**Rules under test:** only Economic Times, Business Standard, Mint, Moneycontrol, The Hindu BusinessLine, Financial
Express, CNBC-TV18 and Reuters; last 30 days; newest first; the same story once; at most 20.
**Automated:** `test_news_prices.py`. **Manual:** open any report and confirm every news item names one of those
outlets and has a working link. Small and mid caps often show 0 to 2 items: that is the filter, not a bug.
When there are none the news row still reads green but says "No headlines from trusted outlets in the last 30 days."

### 2.7 AI: headline labeller, report writer, citation checker
**What it does:** the labeller marks each headline (about the company? good/bad? serious?); the writer produces
"Overall" and "What the company does" from numbered facts; the checker rejects any text that fails.
**Automated:** `test_ai.py` (every rejection reason), `test_ai_logging.py`.
**Manual:** in a report, hover or click a citation chip such as `F1`: it must open the source of that fact. Read the
"Overall" sentence against the five rows: every number in it must appear in the rows. The words buy, sell, target
and recommend must never appear. If the AI is off or rejected, `ai_text` is `false` and the page says "A written
summary isn't available right now"; the facts and label are unaffected.

### 2.8 Search and report pages (browser)
Open <http://127.0.0.1:8000> and sign in first (section 0.1).

| # | Do | Expect |
|---|---|---|
| 1 | Type `abb` | A list of matches appears after a moment |
| 2 | Press ↓ then Enter | The ABB report opens; the page title shows the company |
| 3 | Press Esc in the search box | The list closes |
| 4 | Click Research with an empty box | Message: "Type a company name or NSE symbol first." |
| 5 | Type `zzzzzz` | "No NSE stock matches that…" |
| 6 | Open the report | Blocks in order: header, Overall, What the company does, five questions, news, "All numbers and where they came from", sources, disclaimer |
| 7 | Each question row | Shows colour **and** an icon **and** a word (Good / OK / Poor / No data) |
| 8 | Click a source link | Opens in a new tab |
| 9 | Click Refresh report | Skeleton loading state, then a fresh report |
| 10 | Go back to Search | The stock is listed under "Stocks you looked at" |
| 11 | Shrink the window to phone width (375 px) | No sideways scrolling |

---

## 3. Phase 2: My stocks

Set up two stocks first (this also builds their reports, taking about 10 to 15 s each):
```powershell
Api POST "/api/holdings" @{symbol="ABB"; shares=10; buy_price=10000}
Api POST "/api/holdings" @{symbol="TITAN"; watching=$true}
```
**Expect:** `HTTP 201 {"symbol":"ABB","name":"ABB India Limited","watching":false,"shares":10,"buy_price":10000.0,"added_at":"2026-11-25T21:17:04+05:30"}`
and, for TITAN, `"watching":true,"shares":null,"buy_price":null`.

### 3.1 Add: every validation rule
All of these must be rejected with these exact messages. **Automated:** `test_holdings_api.py` (44 tests).

| Do | Expect |
|---|---|
| `Api POST "/api/holdings" @{symbol="ABB"; shares=0; buy_price=100}` | `400` "Enter the number of shares as a whole number, 1 or more." |
| same with `shares="50"` (text), `shares=10.5`, `shares=-5`, or `shares` missing | same `400` message |
| `shares=10000001` | `400` "That number of shares looks too large. Check it." |
| `buy_price=-1`, `0`, `"720"` (text), or missing | `400` "Enter your average buy price in rupees, more than 0." |
| `symbol="A B"`, `"../x"`, or 21+ characters | `400` "That doesn't look like an NSE symbol." |
| `symbol="NOSUCH"` | `404` "NOSUCH isn't on the NSE equity list. Check the symbol or search by company name." |
| Add `ABB` a second time | `400` "You already have ABB. Edit it instead." |
| 101st stock | `400` "You can keep up to 100 stocks in v0." |
| Body is not an object, or `watching` is not true/false | `400` "That request wasn't valid." |

**Pass if:** a rejected request saves nothing (check `Api GET "/api/holdings"` afterwards).
Also accepted: lower-case or padded symbols (`" abb "` is stored as `ABB`), `M&M`, and `buy_price` such as `720.456`
(stored as `720.46`). A `watching` stock ignores any shares and price you send.

### 3.2 Edit
```powershell
Api PUT "/api/holdings/ABB" @{shares=20; buy_price=10000}            # 200, shares now 20, added_at unchanged
Api PUT "/api/holdings/ABB" @{symbol="TITAN"; shares=1; buy_price=1} # 400 "The symbol in the form doesn't match the stock being edited."
Api PUT "/api/holdings/INFY" @{shares=1; buy_price=1}                # 404 "INFY isn't in your stocks."
Api PUT "/api/holdings/ABB" @{watching=$true}                        # 200; shares and buy_price become null
Api PUT "/api/holdings/ABB" @{watching=$false; shares=20; buy_price=10000}   # back to owning
```

### 3.3 Delete
`Api DELETE "/api/holdings/TITAN"` → `HTTP 200 {"deleted":true}`; again → `404` "TITAN isn't in your stocks."
Saved reports are kept (the stock still appears in Recent reports).

### 3.4 The holdings view: values, gains, totals, order
**What it does:** `GET /api/holdings` joins your holdings with cached reports and live prices. It **never calls
Screener**, so it is fast.
**Automated:** `test_portfolio.py`. **Manual:** with ABB at 20 shares, bought at ₹10,000:
```powershell
Api GET "/api/holdings"
```
**Expect (price will differ):**
```
"totals":{"invested_display":"₹2,00,000","value_display":"₹1,40,570","gain_display":"-₹59,430 (-29.7%)","direction":"down","excluded":0,"note":null}
ABB row: "price_display":"₹7,028.50","price_source":"live","value_display":"₹1,40,570","gain_display":"-₹59,430 (-29.7%)","direction":"down"
TITAN row: shares/value/gain are null (watching), "price_display":"₹4,686.60"
```
**Check by hand** (this is the point of the exercise):
- value = shares × price → 20 × 7,028.50 = **140,570** ✔
- gain = value − shares × buy price → 140,570 − 200,000 = **−59,430** ✔; percent = −59,430 ÷ 200,000 = **−29.7%** ✔
- Indian grouping: `₹2,00,000`, not `₹200,000` ✔
- Order: flagged stocks first, then largest value, then watching stocks A to Z.
- A stock whose price can't be fetched is left out of the totals and the note says so ("1 stock isn't included
  because its price couldn't be fetched.").
- With no stocks: totals are `₹0`, gain `₹0 (0.0%)`, direction `flat`, `rows` is `[]`.

### 3.5 The "Look at this" flag: the four rules
A stock is flagged when any one is true. The flag explains **why**, never what to do.

| Rule | Fires when | Text shown | How to trigger it by hand |
|---|---|---|---|
| Be careful | latest label is Be careful | `Label is Be careful` | A stock that scores that way, e.g. `IDEA`; TITAN was Be careful on 25 Nov |
| Label got worse | latest label ranks below the previous report's (Looks solid > Mixed > Be careful) and no question newly went grey | `Label went from Looks solid to Mixed` | recipe A below |
| Price drop | price is ≥ 20% below buy price (owned stocks only) | `Price is 29% below what you paid` | Add a stock with a buy price at least 25% above today's price (the ABB example above) |
| Serious news | latest report has a serious headline the previous report didn't, and the previous news source worked | `New serious news since the last refresh` | recipe B below |

**Recipes A and B** (they need two stored reports, which only exist after two refreshes, so we fake the change).
`scripts/craft_report.py` signs in as a **test** Supabase account (see 0.2; the fake server of 0.1 lives in another
process, so it can't be used for this) and adds an invented report copy to that account's history. First add TITAN and ABB
in My stocks as that account, then:
```powershell
venv\Scripts\python.exe scripts\craft_report.py show           TITAN --email test@example.com   # list stored reports
venv\Scripts\python.exe scripts\craft_report.py label-worse    TITAN --email test@example.com   # recipe A
venv\Scripts\python.exe scripts\craft_report.py serious-news   ABB   --email test@example.com   # recipe B
```
(You are asked for the password at a hidden prompt.) Reload My stocks and read each flag.
**Expect after A:** TITAN's flag lists two reasons: `Label is Be careful; Label went from Looks solid to Be careful`.
**Expect after B:** ABB's flag has `New serious news since the last refresh`. The same two rules are covered
exhaustively by `test_flags.py` and `test_craft_report.py`, so this is only for seeing them yourself.

**Boundaries and guards (automated, `test_flags.py`):** exactly 20.00% below fires, 19.99% does not; with only one
report the label and news rules never fire (no false flags on first load); a label that drops *because a question
went grey* (for example the AI was down) is **not** flagged; reports saved before these fields existed never fire.
Also check that none of the four texts contains the word *buy*, *sell*, *target* or *recommend*.

### 3.6 Refresh all
The page refreshes **one stock per request** (so no request runs long) and shows "Refreshing 3 of 10". The single-request
version is still there for scripts:
```powershell
Api POST "/api/refresh-all"
Api POST "/api/holdings/ABB/refresh"     # one stock: {"symbol":"ABB","refreshed":true,"failed":null,"new_flag":false}
```
**Expect:** about 5 to 10 s per stock, then `HTTP 200 {"refreshed":["ABB","TITAN"],"failed":[],"new_flags":[]}`.
- `refreshed`: every stock that was rebuilt. `failed`: stocks that couldn't be, each with a plain reason.
- `new_flags`: stocks that **gained** a flag reason during this refresh (measured before and after).
- If Screener.in can't be reached for a stock, it appears in `failed` with "Screener.in couldn't be reached, so the
  earlier report was kept." and its old report stays in place.
- Two refreshes at once: the second gets `400` "A refresh is already running. Try again in a minute."
- With no stocks: `{"refreshed":[],"failed":[],"new_flags":[]}`.
**Automated:** `test_refresh.py` covers each of these.

### 3.7 My stocks page (browser)
Open <http://127.0.0.1:8000/holdings.html>.

| # | Do | Expect |
|---|---|---|
| 1 | Fresh database | "No stocks yet" with an Add a stock button |
| 2 | Add a stock → Save with nothing chosen | "Choose a stock from the suggestions." |
| 3 | Pick ABB, shares `0` | "Enter the number of shares as a whole number, 1 or more." |
| 4 | Shares `10`, price empty | "Enter your average buy price in rupees, more than 0." |
| 5 | Shares `10`, price `10000`, Save | Dialog closes; "Saved ABB India Limited."; the row appears (this takes 10 to 15 s) |
| 6 | Read the row | Shares × buy price, value today, gain/loss with ▲/▼ and a sign, a label pill, a "Look at this" tag with its reason |
| 7 | Add TITAN with "I don't own it" ticked | Shares and price fields hide; the row says Watching and "Not owned" |
| 8 | Edit ABB | The stock field is locked; shares and price are pre-filled |
| 9 | Edit ABB, tick "I don't own it", Save | A confirmation: "This clears your shares and buy price…"; Cancel returns to the form |
| 10 | Press Esc in a dialog | It closes and focus returns to the button you used |
| 11 | Click Refresh all | "Refreshing N stocks. This takes about 5 seconds per stock."; buttons disabled; then a summary such as "Refreshed 2 stocks. No new flags." |
| 12 | Remove a stock | A confirmation naming it; then "Removed …" |
| 13 | Phone width (375 px) | Each row becomes a card; no sideways scrolling; buttons at least 44 px tall |

---

## 4. Phase 3: Market today

```powershell
$m = ((Api GET "/api/market/today") -replace '^HTTP 200 ','') | ConvertFrom-Json
"as_of=$($m.as_of) indices=$(($m.indices | % { $_.name + ' ' + $_.value_display + ' ' + $_.change_display }) -join '; ') headlines=$($m.headlines.Count) points=$($m.points.Count) ai_text=$($m.ai_text)"
```
**Expect (25 Nov 2026):**
`as_of=25 Nov, 9:18 pm indices=Nifty 50 25,819 +1.8%; Sensex 83,938 +1.8% headlines=10 points=3 ai_text=True`
The first call takes about 12 s (three sources and an AI call); an immediate second call takes about 0.1 s (cache).

### 4.1 Index levels
**Rule:** Nifty 50 (`^NSEI`) then Sensex (`^BSESN`), level with Indian grouping, change vs the previous close.
**Automated:** `test_market_sources.py`. **Manual (E3.6):** compare with a live source such as NSE or Google
Finance at the same moment; they should agree to within 0.1%. After the close and at weekends they show the **last
session** (the page says so). One index failing leaves the other; both failing shows "Couldn't fetch the index
levels right now."

### 4.2 Headlines
**Rules:** ET Markets and Business Standard feeds, last 24 hours, newest first, the same story once, exactly 10
shown as `H1`…`H10`, times in India time (`7:19 pm` today, `24 Nov, 9:05 pm` earlier).
**Automated:** `test_market_sources.py` on saved real feeds. **Manual:** open a few headlines; each link must work
and match its title.

### 4.3 "What happened today" (AI points)
**Rules:** at most 3 points; every sentence ends with a chip like `H4` that opens that headline; only headlines
that are on the page can be cited; any number must come from the headlines or the index figures; no advice words;
no guessing a cause the headlines don't state.
**Automated:** `test_market_ai.py` (16 rejection cases, each followed by a retry).
**Manual (E3.7), do this on at least two days:** for each point click its chip and read the headline. Pass only if
the headline really says what the point says. Example from 25 Nov: the point "The RBI recorded net dollar purchases
of $6.94 billion in September, its fourth straight month" cites `H5`, "RBI net buyer of dollars for fourth straight
month in September, data shows": it matches. If AI is off the block reads "A written summary isn't available right
now" and nothing else changes.

### 4.4 Your stocks in the news
**Rule:** compares each saved stock (owned or watching) with the **titles** of all headlines from the last 24 hours
(not only the 10 shown), by company-name phrase (`ABB India`) or the all-caps ticker (`IDEA`). At most 3 headlines per
stock and 10 rows in all. If the headline is one of the shown ten it says which (`H4`).
**Automated:** `test_matching.py`. The deliberate non-matches show the limits:

| Headline | Stock | Match? |
|---|---|---|
| "ABB India logs record Q3 orders" | ABB | yes |
| "ABB shares jump after strong results" | ABB | yes (ticker in capitals) |
| "Infosys's results beat estimates" | INFY | yes |
| "Bajaj Finserv Q2 profit rises" | BAJFINANCE (Bajaj Finance) | **no**, a different company |
| "Tata Steel plans new plant" | TATAMOTORS | **no** |
| "It is not a good idea to chase rallies" | IDEA | **no** (lower-case word) |
| "India's reliance on imported oil grows" | RELIANCE | **no** |
| "SBI hikes lending rates" | SBIN (State Bank of India) | **no**: aliases like SBI and HUL are not matched in v0 |

**Manual (E3.8), on at least three different days:** add a stock you know is in the news, open Market today, and
confirm it appears under "Your stocks in the news" with the right headline and **no wrong matches**. Known
limitation: ET sometimes publishes generic "Share Price Highlights" pages that match by name.

### 4.5 Watching
Stocks added with "I don't own it" appear A to Z with their label (or "No report yet") and a link to their report.
Check each link opens the right report (E3.9). Stocks you own do not appear here.

### 4.6 Cache
**Rule (decision D9):** the market part (indices, points, headlines) is cached for 15 minutes; **Your stocks and
Watching are always recomputed**, so adding a stock shows up immediately.
```powershell
Measure-Command { Api GET "/api/market/today" | Out-Null } | % { "first: {0:n1}s" -f $_.TotalSeconds }
Measure-Command { Api GET "/api/market/today" | Out-Null } | % { "second: {0:n2}s" -f $_.TotalSeconds }
Measure-Command { Api GET "/api/market/today?refresh=true" | Out-Null } | % { "refresh: {0:n1}s" -f $_.TotalSeconds }
```
**Expect:** slow, near 0 s, slow. A page where every source failed is **not** cached, so the next load retries.
`?refresh=maybe` → `400` "That request wasn't valid." **Automated:** `test_market_endpoint.py` counts the calls.

### 4.7 Market today page (browser)
Open <http://127.0.0.1:8000/market.html>.

| # | Do | Expect |
|---|---|---|
| 1 | Load | Blocks in order: Market move, What happened today, Top headlines, Your stocks in the news, Watching, Where this came from |
| 2 | Index cards | Level, ▲/▼ and a percentage; "Source: Yahoo Finance" is a link |
| 3 | Click a chip in a point | Opens the cited headline in a new tab |
| 4 | Top headlines | Ten, with ids `H1`…`H10`, outlet and time |
| 5 | No saved stocks | "None of your stocks are in today's headlines…" and "Stocks you mark as watching… appear here." |
| 6 | Click Refresh | Skeleton loading state, then the page |
| 7 | Phone width | No sideways scrolling |

---

## 5. Breaking things on purpose

Each page must still open when something fails. Only the dependent part may go grey.

### 5.1 All outside sources down
Start the fake-login server (0.1) with outgoing connections pointed at a dead proxy. The fake Supabase is inside the
process, so signing in and saving still work while every data source fails (this was verified for the sources):
```powershell
$env:ALLOW_FAKE_SUPABASE = "1"
$env:HTTPS_PROXY = "http://127.0.0.1:9"; $env:HTTP_PROXY = "http://127.0.0.1:9"; $env:NO_PROXY = "127.0.0.1,localhost"
venv\Scripts\python.exe scripts\dev_fake_server.py 8001
```
In another window (variables cleared; `$Base = "http://127.0.0.1:8001"`, then `Login ...`):
```powershell
Api GET "/api/market/today?refresh=true"
```
**Expect:** `HTTP 200`, `indices: []`, `headlines: []`, `points: []`, `ai_text: false`, and all three sources `"ok": false`
(about 3 s). In the browser the report page still opens, with grey rows and a sources footer naming what failed; the
company list falls back to the bundled snapshot, so search still works. Close both windows afterwards.

### 5.2 AI off
Leave `LABELLER_MODEL` and `WRITER_MODEL` empty in `.env` (edit it yourself; the assistant never reads it) and
restart. **Expect:** the report's "Overall" says a written summary isn't available, the news row is grey ("Couldn't
check the headlines right now."), `ai_text` is `false`, **and the server window prints a warning saying why**
(for example "Report writing skipped: the OpenAI key or WRITER_MODEL isn't configured."). Market today shows
headlines without points. Nothing crashes.

### 5.3 One source down
Not practical by hand; use the automated tests, which fake each source separately:
`test_report.py` (Screener down, news down, price falls back, AI down, bad AI text),
`test_refresh.py` (Screener down keeps the old report), `test_market_endpoint.py` (one index down, one feed down,
both feeds down, AI down, everything down).

### 5.4 Rate limiting
Google News may answer HTTP 429 after many rapid requests (seen during development). **Expect:** the news question
turns grey, the rest of the report is unaffected. Wait a few minutes and use Refresh report.

---

## 6. Exit-criteria checklist
From `Documents/Architecture/V0_Phase2_Phase3_Spec.md`. **Auto** rows are covered by the suite (run it, section 1);
**You** rows are for you to tick.

| Criterion | Where | Type |
|---|---|---|
| E2.1 holdings and refresh-all contracts and messages | 3.1–3.3, 3.6; `test_holdings_api.py` | Auto |
| E2.2 flag rules, boundaries, outage guard | 3.5; `test_flags.py` | Auto |
| E2.3 holdings maths | 3.4; `test_portfolio.py` | Auto |
| E2.4 refresh-all behaviour | 3.6; `test_refresh.py` | Auto |
| E2.5 holdings view never calls Screener, fast | 3.4; `test_portfolio.py` | Auto + time it once |
| **E2.6 totals match your broker within 0.5%** | 3.4, with your real stocks | **You** |
| **E2.7 every row opens the right report** | 3.7 | **You** |
| **E2.8 flags appear for the right reasons on live data** | 3.5 (high buy price; IDEA) | **You** |
| E2.9 no false flags on first load | 3.5; `test_flags.py` | Auto + glance |
| E2.10 browser pass, desktop and 375 px | 3.7 | You (checklist) |
| E2.11 bad input rejected, no script injection | 3.1; `test_holdings_api.py` | Auto |
| E2.12 suite green, README updated | section 1 | Auto |
| E3.1 market contract and degradation | 4, 5; `test_market_endpoint.py` | Auto |
| E3.2 feed parsing on real samples | 4.2; `test_market_sources.py` | Auto |
| E3.3 market writer rejections | 4.3; `test_market_ai.py` | Auto |
| E3.4 matching: 10+ true and 10+ look-alikes, no errors | 4.4; `test_matching.py` | Auto |
| E3.5 caching call counts | 4.6; `test_market_endpoint.py` | Auto |
| **E3.6 index levels within 0.1% of a live source; cold load under 20 s** | 4.1 | **You** |
| **E3.7 each point matches its cited headline (2 days)** | 4.3 | **You** |
| **E3.8 your stocks appear when in the news (3 days)** | 4.4 | **You** |
| **E3.9 Watching lists every watched stock, links work** | 4.5 | **You** |
| E3.10 browser pass, desktop and 375 px | 4.7 | You (checklist) |
| E3.11 suite green, README updated | section 1 | Auto |

---


### V1 platform (from `Documents/Architecture/V1_Platform_Spec.md`)
| Criterion | Where | Type |
|---|---|---|
| 1.1 The existing tests pass on the in-memory store; one contract suite runs on both stores | `test_store_contract.py`; with the `TEST_SUPABASE_*` variables it also runs against real Supabase | Auto (real Supabase: **You**) |
| 1.2 Row-level security: nobody sees or changes another account's rows; nothing readable without a login | `test_store_contract.py` (fake server for offline, **real project** for proof) | Auto + **You** (run against a test project) |
| 1.3 No secret / service-role key anywhere in the repo | `test_store_supabase.py` | Auto |
| 1.4 Copied data gives identical totals | `scripts/copy_sqlite_to_supabase.py` is **not built** (the local database has no data worth moving, per your choice to start fresh; say if you want it) | n/a |
| 1.5 Database unreachable shows the plain 503 message | `test_auth_routes.py` | Auto |
| 2.1 Every route except `/api/health` and login returns 401 without a cookie | `test_auth_routes.py::test_every_data_route_is_closed_without_a_session` | Auto |
| 2.2 Same message for wrong password and unknown email; tokens never in logs or responses; cookie flags | `test_auth_routes.py` | Auto |
| 2.3 Logout ends only that device; a request from another site is refused | `test_auth_routes.py`, 7.1 | Auto |
| 2.4 Two simultaneous requests at token expiry both succeed | `test_auth_routes.py`, `test_auth_provider.py` | Auto |
| 3.1 Vercel preview and production complete a report, a refresh and the market page | 7.6 | **You** |
| 3.2 Works on a real iPhone and Android, also after closing and reopening | 7.3, 7.6 | **You** |
| 3.3 README lists the accepted limits and costs | `Deploy_Guide.md` ("Costs and limits") | Auto (doc) |
| 4.1 Every operation over 0.3 s shows a loader; Refresh all shows "N of M"; reduced motion | `run_browser_checks.py loaders`, 7.2 | Auto + **You** (Slow 4G) |
| 5.1 No sideways scroll at 320–768 px; inputs 16 px; tap targets 44 px | `run_browser_checks.py mobile`, 7.3 | Auto + **You** (real phone) |
| 5.2 Lighthouse mobile scores; Add to Home Screen | **not measured by me**: run Lighthouse in Chrome on the deployed site; 7.3 step 9 | **You** |
| 6.1 axe-core: zero serious or critical issues | `run_browser_checks.py axe` | Auto |
| 6.2 Keyboard-only run, visible focus, no traps | `run_browser_checks.py a11y`, 7.4 | Auto + **You** |
| 6.3 Back link and browser Back from all three entry points | `run_browser_checks.py a11y`, 7.5 | Auto + **You** |
| 6.4 NVDA and VoiceOver announce titles, loaders, errors, the card layout | 7.4 steps 7 to 10 | **You** (listen) |

---

## 7. Platform walkthroughs: sign-in, loaders, phone, keyboard, Back, deployment

Do these in a browser, the way a person would. Use the fake server (0.1) unless a row says otherwise.

### 7.1 Signing in and out
| # | Do | Expect |
|---|---|---|
| 1 | Open <http://127.0.0.1:8000> in a fresh private window | You are sent to the **Sign in** page; there is no menu |
| 2 | Open `/holdings.html` directly | Sign in page; the address ends with `?next=%2Fholdings.html` |
| 3 | Press Sign in with both fields empty | "Enter your email and password."; the cursor is in the first empty field |
| 4 | Email filled, password empty, Sign in | The same message; the cursor is in the password field |
| 5 | Enter the wrong password | "Wrong email or password."; the password box is emptied; the button is back to "Sign in" |
| 6 | Use an email nobody has, any password | The very same message (it never says which part was wrong) |
| 7 | Click **Show**, then **Hide** | The password becomes visible, then hidden again |
| 8 | Enter the right details | You land on **My stocks** (where you were going); your email and **Log out** are top right |
| 9 | Reload the page, or close the tab and reopen the site | Still signed in |
| 10 | Open `/login.html` while signed in | Straight to the page you were heading for |
| 11 | Open `/login.html?next=https://evil.example` while signed in | Goes to the home page, never to another site |
| 12 | Get the password wrong 5 times in a row, then use the right one | "Too many attempts. Try again in a few minutes." even for the right password |
| 13 | Press **Log out** | You see "Logging out…", then the Sign in page |
| 14 | Press the browser Back button, then reload | Sign in page again (nothing of your data is shown) |
| 15 | Sign in as `partner@example.com`, add a stock; log out; sign in as `dev@example.com` | Each person sees only their own stocks |
| 16 | Browser developer tools > Application | Cookies `sb-access` and `sb-refresh` are marked **HttpOnly**; Local storage and Session storage are empty |

### 7.2 Loaders (something slow always shows a spinner and words)
In the browser's developer tools open **Network** and set throttling to **Slow 4G** (or use a real slow connection).
| # | Do | Expect |
|---|---|---|
| 1 | Press Sign in | The button turns into a spinner and "Signing in…" and can't be pressed twice |
| 2 | Open Search; watch "Stocks you looked at" | A spinner and "Loading your stocks…", then the list |
| 3 | Type `abb` | A small spinner inside the box and "Searching…" until the suggestions appear |
| 4 | Open a report you haven't opened today | A heading "Report for ABB", a spinner with "Getting the report. A new one can take up to a minute.", grey placeholders. After 8 s the words change to "This is taking longer than usual. Still working…" and a seconds counter appears |
| 5 | My stocks > Add a stock > Save | The Save button shows a spinner and "Saving…" |
| 6 | My stocks > **Refresh all** | A spinner and "Refreshing 1 of N: ABB. This takes about 5 seconds per stock." counting up; the buttons are disabled meanwhile; a summary at the end |
| 7 | Remove a stock | "Removing …" with a spinner, then "Removed …" |
| 8 | Market today | A heading, a spinner with "Getting today's market…", then the page |
| 9 | Turn your device's **Reduce motion** setting on, repeat step 8 | The spinner does not spin, but the words are still there |
| 10 | Developer tools > Network > **Offline** | A banner "You're offline. Some things won't work until you reconnect."; a search says "You're offline. Reconnect and try again." |
| 11 | Back online | The banner disappears |

### 7.3 On a phone (or developer tools > device mode: iPhone 12, Pixel 7, and a 320-wide window)
| # | Do | Expect |
|---|---|---|
| 1 | Open every page | No sideways scrolling anywhere; nothing is cut off at the right edge |
| 2 | Look at the bottom of the screen | Three tabs with icons: **Search**, **My stocks**, **Market today**; the current one has a line above it |
| 3 | Tap each tab | It goes there; the tab bar stays reachable with your thumb and clears the phone's bottom edge |
| 4 | Tap into the email or search box on an iPhone | The page does **not** zoom in |
| 5 | My stocks | Each stock is a card; every line has its label ("Shares and buy price", "Value today" …) |
| 6 | Tap **Add a stock** | A sheet slides up from the bottom, full width, with big fields and buttons |
| 7 | Tap the small `F1` style source chips in a report | They open the source easily (the tap area is bigger than the chip) |
| 8 | Rotate the phone | Layout adapts, nothing breaks |
| 9 | Phone browser menu > **Add to Home Screen** | The app gets the "SA" icon and opens full-screen without browser bars |
| 10 | Close the app and reopen it | Still signed in |

### 7.4 With the keyboard only (put the mouse away) and a screen reader
| # | Do | Expect |
|---|---|---|
| 1 | Load any page and press **Tab** once | A "Skip to main content" button appears at the top left |
| 2 | Press **Enter** on it | The menu is skipped and you are at the page content |
| 3 | Keep pressing Tab | Every link, button and field is reached in a sensible order, each with a clear focus ring; you never get stuck |
| 4 | Sign in, search `abb`, use **↓** and **Enter** | You reach the report without the mouse |
| 5 | In the Add dialog press **Esc** | It closes and the cursor returns to the button you used |
| 6 | Leave the shares field as `0` and press Save | The error is read out, and **only** the shares field is marked invalid and focused |
| 7 | (NVDA on Windows, or VoiceOver on iPhone) open My stocks | You hear "Your stocks are ready. N stocks." The list is announced as a table with rows and labelled cells |
| 8 | Press the heading key (H) on a report | Headings read in order: the company, then each section |
| 9 | Move to an external link, such as a source | You hear that it opens in a new tab |
| 10 | Press Refresh on a report | You hear the loader's words; at the end focus is on the report's heading |

### 7.5 Going from page to page and back
| # | Do | Expect |
|---|---|---|
| 1 | Search > type `abb` > open the report | The report has a **← Back to Search** link at the top |
| 2 | Click that link (or the browser Back button) | You are back on Search with `abb` still typed and the suggestions showing; the address says `?q=abb` |
| 3 | My stocks > click a stock's name | The report says **Back to My stocks**, and the menu highlights **My stocks**, not Search |
| 4 | Click Back | My stocks, as you left it |
| 5 | Market today > click a stock under "Your stocks in the news" | **Back to Market today**; Back returns there |
| 6 | Open a report address directly | **Back to Search** |
| 7 | Browser Back and Forward across a few pages | Each page comes back quickly and correctly |
| 8 | Signed out, open `/report.html?symbol=ABB`, sign in | You land on that report |

### 7.6 The deployed site
Follow the first-run checklist in `Documents/Deployment/Deploy_Guide.md` (Part D), then repeat 7.1 to 7.5 on the Vercel
address, on a **real iPhone and a real Android phone**. Also confirm: the cookies exist after signing in (developer tools
> Application > Cookies shows `__Host-sb-access`), and saving a stock works (if you see "That request wasn't allowed from
this site.", add the Vercel address to `ALLOWED_ORIGINS` in Railway).

### 7.7 The automated browser checks
Everything in 7.1 to 7.5 that can be checked by a script is checked by the browser suite, which starts a fresh fake
server for each check:
```powershell
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
venv\Scripts\python.exe -m playwright install chromium         # once
venv\Scripts\python.exe scripts\run_browser_checks.py           # all six, about 10 to 15 minutes (real data sources)
venv\Scripts\python.exe scripts\run_browser_checks.py mobile a11y   # just some
```
| Check | What it covers |
|---|---|
| `login` | Sign-in, the guard on every page, Log out, return-to-page, open-redirect protection, HttpOnly cookies, nothing in browser storage, two accounts kept apart |
| `loaders` | A spinner and words for every slow operation (responses are deliberately delayed), the 8-second message, offline banner, reduced motion |
| `mobile` | 320, 375, 390, 412 and 768 px on every page and dialog: no sideways scroll, inputs 16 px, tap targets 44 px, bottom tab bar, bottom-sheet dialogs |
| `a11y` | Skip link, keyboard-only sign-in, a visible focus ring on every stop, no keyboard trap, Back from all three entry points, announcements and focus, form errors, phone card semantics |
| `axe` | The axe-core scanner on every page and state at desktop and phone size: fails on any serious or critical finding (currently zero findings of any level) |
| `csp` | The exact Content-Security-Policy from `frontend/vercel.json`: zero violations on every page, fonts still load, an injected script and an outside frame are blocked |

Screenshots go to `scripts/browser/output/` (not tracked by git). Exit code 1 if anything fails.

---

## 8. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| "A written summary isn't available right now" on every report | AI not configured, a wrong model name, or the output failed the check. Look at the **server window**: it logs the reason. Restart after editing `.env` (it is read once at startup). Reports cached for 24 h keep their old text: click Refresh report |
| News row grey, "Couldn't fetch this right now" | Google News rate limit (429) or no internet; wait and refresh |
| `₹` shows as `â¹` in PowerShell | Use the helper in 0.2, or run `[Console]::OutputEncoding = [Text.Encoding]::UTF8` |
| `Api` prints `HTTP 400` with nothing after it | You pasted an older helper; use the one in 0.2 (it reads `$_.ErrorDetails.Message`) |
| `Address already in use` | Another server is on that port: use another one (for example `8002`), or stop the old one |
| `Api` prints `HTTP 401 ... Please sign in.` | You haven't run `Login` in this window, or you logged out |
| `craft_report.py` says "Set SUPABASE_URL …" | It signs in to a real **test** account (0.2); it can't use the fake server |
| The browser checks say `Executable doesn't exist` | Run `python -m playwright install chromium` once, or set `CHROME_PATH` |
| Totals say "isn't included" | That stock's price couldn't be fetched (Yahoo down and no price in its report). Refresh all, then reload |
| Search says "Couldn't fetch the NSE company list" | First run with no internet and an empty database; connect and retry |
| Tests fail only on your machine | Run `venv\Scripts\python.exe -m pip install -r requirements.txt` then `pytest` again |
