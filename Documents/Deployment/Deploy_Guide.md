# Deploy guide: Supabase + Railway + Vercel

Written for the person setting this up (you). About 45 minutes the first time. Do the parts in order.

```
Your phone / browser ──> Vercel (the pages)  ──/api/*──>  Railway (the backend)  ──>  Supabase (login + your data)
```

**Rules that keep this safe**
- You only ever need Supabase's **Project URL** and **publishable (anon) key**. Do **not** create or use a *secret* or
  *service_role* key anywhere. The app is built so it never needs one, and a test fails if one appears in the repo.
- Put values into Railway's Variables screen or your own terminal. Never paste keys into a chat, a commit or a file in
  the repo. (`.env` is ignored by git.)
- Dashboard labels change over time. Where I name a button or setting below, I wrote it from Supabase's, Railway's and
  Vercel's documentation, not from their live screens; if a label differs, look for the closest one.

---

## Part A: Supabase (about 15 minutes)

1. **Create a project** (dashboard > New project). Pick the region nearest you and save the database password
   somewhere safe (the app doesn't use it, but you can't see it again).
2. **Copy two values** from *Project Settings > API* (or the **Connect** dialog): the **Project URL**
   (`https://<ref>.supabase.co`) and the **publishable key** (`sb_publishable_...`). Ignore any secret key.
3. **Create the tables.** Open *SQL Editor > New query*, paste the whole of [supabase/schema.sql](../../supabase/schema.sql)
   and press **Run**. Expect "Success". In *Table Editor* you should see `holdings` and `reports`, each marked as having
   Row Level Security on. It is safe to run the file again later.
4. **Lock sign-ups.** *Authentication* > the sign-in settings:
   - turn **off** "Allow new users to sign up" (so only people you add can have an account),
   - leave **anonymous sign-ins off**,
   - set the minimum password length to **10** or more.
5. **Create your account.** *Authentication > Users > Add user > Create new user*: your email and a strong password,
   and tick **Auto Confirm User** (no email is sent). Do the same for anyone else you want to let in.
6. *(Recommended, for tests)* Create a **second, empty Supabase project** and repeat steps 1 to 3 there, plus two test
   accounts. Real-database tests use it so they never touch your real data (see "Running the real-database tests").

**Check it:** in the SQL Editor run `select count(*) from public.holdings;`. It should say 0.

---

## Part B: Railway, the backend (about 15 minutes)

You have a premium plan, so the service stays awake.

1. **New Project > Deploy from GitHub repo** and choose this repository. Railway builds the `Dockerfile` in the repo
   root automatically (documented: it uses a Dockerfile whenever one exists).
2. **Variables** (the service's *Variables* tab). Add:

   | Name | Value |
   |---|---|
   | `SUPABASE_URL` | your Project URL |
   | `SUPABASE_PUBLISHABLE_KEY` | your publishable key |
   | `COOKIE_SECURE` | `true` |
   | `ALLOWED_ORIGINS` | your Vercel address, e.g. `https://my-app.vercel.app` (add it after Part C, then redeploy) |
   | `OPENAI_API_KEY` | your key (use *Seal* on it so it can't be read back) |
   | `LABELLER_MODEL` | e.g. `gpt-6-luna` |
   | `WRITER_MODEL` | e.g. `gpt-6.2-sol` |

   Railway stages variable changes: review and **Deploy** them.
3. **Public address:** *Settings > Networking > Generate Domain*. Copy it (`https://<name>.up.railway.app`).
4. **Health check:** *Settings > Deploy*, set the healthcheck path to `/api/health`.
5. **Check it:** open `https://<your-railway-domain>/api/health`. You should see `{"ok":true}`. Then
   `https://<your-railway-domain>/api/holdings` should say `{"error":{"code":"unauthorized","message":"Please sign in."}}`.
   That second message is correct: nothing is readable without logging in.

> **Unknowns I could not test from here, so please watch the first deploy:** (1) the image build itself (Docker wasn't
> running on my machine), (2) whether the app can reach Screener.in, Yahoo, Google News and NSE from Railway's network
> (some sites block data-centre addresses), and (3) the listener address (`--host 0.0.0.0`; an IPv6-only `::` listener gave 502 "Application failed to respond"). Open a report for ABB on the deployed site
> and read the sources footer: it names any source that failed.

---

## Part C: Vercel, the pages (about 10 minutes)

1. Edit [frontend/vercel.json](../../frontend/vercel.json): replace `REPLACE-WITH-YOUR-RAILWAY-DOMAIN` with your Railway
   domain (no `https://`, so the line reads `"destination": "https://<name>.up.railway.app/api/:path*"`). Commit and push.
2. In Vercel: **Add New > Project**, import the same repo. Set **Root Directory** to `frontend`, **Framework Preset** to
   *Other*, and leave the build and install commands empty. Deploy.
3. Add your Vercel address to Railway's `ALLOWED_ORIGINS` (Part B step 2) and redeploy the backend. Without this, changes
   such as saving a stock are refused with "That request wasn't allowed from this site."
4. **Check the one thing the docs don't promise:** open your Vercel site, sign in, then in the browser's developer tools
   (*Application > Cookies*) confirm `__Host-sb-access` and `__Host-sb-refresh` exist. If they don't, Vercel isn't
   passing cookies through its proxy. Tell me; the fallback is to serve the pages from Railway itself (the app already
   can), and drop Vercel.

**Known limit:** Vercel stops proxied requests after **120 seconds**. Every request here is shorter (Refresh all runs one
stock at a time), but a very slow data source could still exceed it for one stock.

---

## Part D: your first-run checklist

| # | Do | Expect |
|---|---|---|
| 1 | Open your Vercel address | You're sent to the Sign in page |
| 2 | Sign in with the account from Part A step 5 | You land on Search; your email and **Log out** appear top right |
| 3 | Search `abb`, open the report | A report in about 15 s |
| 4 | My stocks > Add a stock | It saves, and survives a page reload |
| 5 | Refresh all | "Refreshing 1 of N…" then a summary |
| 6 | Market today | Index levels, headlines, points |
| 7 | Log out, then open My stocks | Back at Sign in |
| 8 | Open the site on your phone | Same, in the phone layout |
| 9 | Sign in as a second account | None of the first account's stocks |

---

## Running the real-database tests (optional, recommended)

These prove Row Level Security against a real project. Use the **second** Supabase project from Part A step 6, never your
real one. In your own terminal (not in a file in the repo):

```powershell
$env:TEST_SUPABASE_URL = "https://<test-ref>.supabase.co"
$env:TEST_SUPABASE_PUBLISHABLE_KEY = "<test publishable key>"
$env:TEST_USER_A_EMAIL = "a@example.com";  $env:TEST_USER_A_PASSWORD = "<password>"
$env:TEST_USER_B_EMAIL = "b@example.com";  $env:TEST_USER_B_PASSWORD = "<password>"
venv\Scripts\python.exe -m pytest backend/tests/test_store_contract.py -q
```
Instead of 21 skipped tests you should see them all run and pass. They delete everything in those two test accounts
before and after.

---

## Costs and limits you are accepting

| | |
|---|---|
| Railway | Your plan. One backend instance only: caches (company list, Screener pages, market page) live in memory and reset on every deploy or restart. |
| Vercel | Free Hobby plan is enough for this. Proxy limit 120 s per request. |
| Supabase | Whatever plan you chose. On the **Free** plan a project is paused after 1 week of inactivity and has a 500 MB database; the app shows "The database isn't reachable right now" until you resume it in the dashboard. Each user keeps at most 100 stocks and 10 reports per stock, so it stays tiny. |
| OpenAI | Roughly one US cent or less per fresh report. |

## If something goes wrong

| You see | Likely cause |
|---|---|
| Signing in loops back to the Sign in page | Cookies aren't reaching the backend: check Part C step 4. On plain-http local development set `COOKIE_SECURE=false`. |
| "That request wasn't allowed from this site." | Your Vercel address isn't in Railway's `ALLOWED_ORIGINS`. |
| "The database isn't reachable right now." | Supabase paused or the URL or key is wrong; or `supabase/schema.sql` wasn't run (the Railway logs say "missing grant or policy"). |
| "Sign-in isn't available right now." | `SUPABASE_URL` or `SUPABASE_PUBLISHABLE_KEY` is missing or wrong in Railway. |
| "Too many attempts. Try again in a few minutes." | 5 wrong passwords for an email in 5 minutes. Wait, or check you're using the right account. |
| Reports show grey rows and "Couldn't fetch this right now." | A data source is blocking Railway or is down; the sources footer names which. |
| A summary is missing | OpenAI isn't configured or the output failed the check. The Railway logs say why (no key is ever logged). |
