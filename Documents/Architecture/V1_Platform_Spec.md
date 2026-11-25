# V1 platform spec: Supabase Auth + RLS, online hosting, mobile, loaders, accessibility

Status: **approved plan, in progress.** Extends [V0_Description.md](V0_Description.md) and
[V0_Phase2_Phase3_Spec.md](V0_Phase2_Phase3_Spec.md). Where they disagree, this file wins for everything it covers.

## 1. Architecture

```
Phone / browser ──> Vercel (static frontend; /api/* rewritten) ──> Railway (FastAPI, one instance) ──> Supabase
                                                                          │                            (Auth + 2 RLS tables)
                                                                          └─> Screener, Yahoo, Google News, NSE, ET, BS, OpenAI
```

- The **browser never talks to Supabase**. It calls our API; the backend talks to Supabase.
- The backend holds **only the Supabase URL and the publishable (anon) key. No secret / service-role key exists in
  this project**, so nothing can bypass Row Level Security. Every database call carries the signed-in user's own
  access token, so Postgres RLS decides which rows are visible.
- Login is **Supabase Auth, email + password**. There is no sign-up page; accounts are created in the Supabase
  dashboard (Authentication > Users > Add user, "Auto Confirm"), and public sign-ups and anonymous sign-ins are off.
- The backend keeps the Supabase tokens in **HttpOnly cookies** (`sb-access`, `sb-refresh`). Vercel rewrites
  `/api/*` to Railway so the cookies are first-party (iPhone Safari blocks cross-site cookies).
- **Per-request, stateless Supabase clients** (`persist_session=False`, `auto_refresh_token=False`): a shared client
  would hold one user's session and could hand it to another user.

## 2. What lives where

| Data | Where | Why |
|---|---|---|
| Holdings (per user) | Supabase table `holdings`, RLS | private |
| Stored reports (per user, newest 10 per stock) | Supabase table `reports`, RLS | private; flags compare the two newest |
| NSE company list | backend memory, bundled CSV snapshot as fallback | public data; the backend cannot safely write shared tables without a secret key |
| Cached Screener pages (24 h) | backend memory (size-capped) | public data |
| Market-page cache (15 min) | backend memory | public data |

Consequences stated plainly: caches reset on a restart or deploy (one refetch); the app assumes **one backend
instance** (memory caches and the per-process refresh lock); two users viewing the same stock each get their own
stored report, while the Screener page itself is fetched once and shared in memory.

## 3. Database (`supabase/schema.sql`, pasted once into the Supabase SQL Editor)

```sql
holdings(id bigserial primary key,
         user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
         symbol text not null, shares integer, buy_price double precision,
         watching boolean not null default false, added_at text not null,
         unique (user_id, symbol),
         check (watching or (shares is not null and buy_price is not null and shares > 0 and buy_price > 0)))
reports(user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
        symbol text not null, generated_at text not null, label text, report_json jsonb not null,
        primary key (user_id, symbol, generated_at))
```
- Both tables: RLS enabled; policies **to authenticated** for select, insert, update, delete using
  `(select auth.uid()) = user_id`; insert and update also `with check ((select auth.uid()) = user_id)`.
- Grants: `select, insert, update, delete` to `authenticated` **only**. Nothing for `anon`.
- Never use `user_metadata` in a policy. Never add `SECURITY DEFINER` functions.
- Timestamps stay ISO text as in v0 (no behaviour change). Supabase returns at most 1,000 rows per request; a user has
  at most 100 stocks and 10 reports per stock.

## 4. API contracts (new and changed; everything else unchanged)

| Endpoint | Request | Success | Errors (exact messages) |
|---|---|---|---|
| `POST /api/auth/login` | `{"email","password"}` | 200 `{"user":{"email":"..."}}` + cookies | 400 `bad_request` "Enter your email and password." · 401 `unauthorized` "Wrong email or password." · 429 `rate_limited` "Too many attempts. Try again in a few minutes." |
| `POST /api/auth/logout` | none | 200 `{"ok":true}`; cookies cleared; fine when signed out; signs out **this device only** | none |
| `GET /api/auth/me` | none | 200 `{"user":{"email":"..."}}` | 401 `unauthorized` "Please sign in." |
| every other `/api/*` except `/api/health` | | unchanged | 401 `unauthorized` "Please sign in." |
| `POST /api/holdings/{symbol}/refresh` | none | 200 `{"symbol","refreshed":true,"failed":null,"new_flag":false}`; on Screener failure `refreshed:false`, `failed:{"reason":"Screener.in couldn't be reached, so the earlier report was kept."}` | 404 `not_found` "{SYM} isn't in your stocks." |
| `GET /api/reports/recent` | | now the signed-in user's stocks | |

- Error codes added: `unauthorized` (HTTP 401), `rate_limited` (HTTP 429). Database trouble: 503 `source_unavailable`
  "The database isn't reachable right now. Try again in a minute."
- **Cookies:** `HttpOnly`, `Secure` when `COOKIE_SECURE=true`, `SameSite=Lax`, `Path=/`. Local http development uses
  `COOKIE_SECURE=false`.
- **CSRF:** POST/PUT/DELETE need `Content-Type: application/json` and, when an `Origin` header is present, it must be
  in `ALLOWED_ORIGINS` (the local server also allows its own origin).
- **Token use:** every request verifies the access token with Supabase (cached about 60 s). When it is near expiry the
  backend renews it from the refresh token (refresh tokens are single-use, so a per-session lock stops simultaneous
  requests from burning it) and sets fresh cookies.
- **Refresh all** is one request per stock from the UI (Vercel's proxy limit is 120 s). `POST /api/refresh-all` stays
  for scripts.
- Out of scope: sign-up page, password reset emails, MFA, social login.

## 5. Configuration (names only; values are never committed or read by the assistant)

`SUPABASE_URL` · `SUPABASE_PUBLISHABLE_KEY` · `ALLOWED_ORIGINS` · `COOKIE_SECURE` · existing `OPENAI_API_KEY`,
`LABELLER_MODEL`, `WRITER_MODEL`. Tests of the real database use `TEST_SUPABASE_URL`, `TEST_SUPABASE_PUBLISHABLE_KEY`,
`TEST_USER_A_EMAIL/PASSWORD`, `TEST_USER_B_EMAIL/PASSWORD` (a separate, empty Supabase project is recommended).

## 6. Exit criteria

**Data and login**
- 1.1 The existing tests pass on the in-memory store; one contract suite runs the same checks against real Supabase.
- 1.2 **RLS proof (two real accounts):** with no login nothing is readable; account A cannot read, change, delete or
  reassign account B's rows, including by sending B's `user_id`.
- 1.3 The repo and loaded settings contain **no secret / service-role key** (automated check).
- 1.4 Copied holdings give identical totals before and after.
- 1.5 Database unreachable gives the 503 message, never a stack trace.
- 2.1 Every route except `/api/health` and login returns 401 without a cookie (a test walks the route table).
- 2.2 Wrong password and unknown email give the same message; tokens never appear in logs or responses.
- 2.3 Logout ends that device's session only; a bad Origin is rejected.
- 2.4 Two simultaneous requests at token expiry both succeed.

**Online:** 3.1 Vercel preview and production complete a report, a per-stock refresh and the market page through the
proxy · 3.2 works on a real iPhone and Android phone, also after closing and reopening the browser (you tick) ·
3.3 README lists the accepted limits and costs.

**Polish:** 4.1 every operation over 0.3 s shows a loader within 100 ms; Refresh all shows "N of M"; reduced motion
means no spinning but the text remains · 5.1 no sideways scroll at 320, 375, 390, 412, 768 px; inputs at least 16 px;
touch targets at least 44 px · 5.2 Lighthouse mobile: performance 90+, accessibility 95+, layout shift under 0.1; Add
to Home Screen works (you tick) · 6.1 axe-core: zero serious or critical issues · 6.2 full keyboard-only run, no traps
· 6.3 Back link and browser Back behave from all three entry points · 6.4 NVDA and VoiceOver pass (you tick).

## 7. Risks and fallbacks

| Risk | Fallback |
|---|---|
| A data source blocks Railway's IPs | another Railway region, retries and backoff; last resort run the backend at home behind a tunnel |
| Vercel doesn't pass cookies through the rewrite | serve the frontend from Railway as well (FastAPI already can) |
| `supabase-py` can't sign out one device or verify tokens as hoped | call Supabase's Auth REST endpoints with `httpx` for just those calls |
| Supabase pauses an idle project (if on the Free plan) | use it weekly or upgrade; the app shows the 503 message meanwhile |
