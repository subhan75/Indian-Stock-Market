-- Stock Analyst: the two tables the app stores, protected by Row Level Security (RLS).
--
-- HOW TO RUN: Supabase dashboard > SQL Editor > New query > paste this whole file > Run.
-- It is safe to run more than once (it only creates what is missing and re-creates the policies).
--
-- Design rules (see Documents/Architecture/V1_Platform_Spec.md):
--   * The app never uses a secret / service-role key. Every database call carries the signed-in user's own
--     token, so these policies are the ONLY thing deciding who sees which row.
--   * Every row belongs to one user (user_id). A signed-in user can only see and change their own rows.
--   * Nothing is granted to the `anon` role, so someone with only the public project URL and anon key can read
--     nothing. Never base a policy on user_metadata (users can edit it); never add SECURITY DEFINER functions.

-- ---------------------------------------------------------------------------------------------- tables
create table if not exists public.holdings (
  id         bigint generated always as identity primary key,
  user_id    uuid    not null default auth.uid() references auth.users (id) on delete cascade,
  symbol     text    not null check (symbol ~ '^[A-Z0-9&-]{1,20}$'),
  shares     integer,
  buy_price  double precision,
  watching   boolean not null default false,
  added_at   text    not null,
  unique (user_id, symbol),
  -- an owned stock needs shares and a price; a watched stock needs neither.
  -- (the "is not null" parts matter: a NULL check result would otherwise count as a pass)
  check (watching or (shares is not null and buy_price is not null and shares > 0 and buy_price > 0))
);

create table if not exists public.reports (
  user_id      uuid  not null default auth.uid() references auth.users (id) on delete cascade,
  symbol       text  not null,
  generated_at text  not null,       -- ISO 8601 text with +05:30, as in v0
  label        text,
  report_json  jsonb not null,
  primary key (user_id, symbol, generated_at)
);

-- newest report first, per user and stock
create index if not exists reports_user_symbol_newest_idx
  on public.reports (user_id, symbol, generated_at desc);

-- ---------------------------------------------------------------------------------------------- RLS
alter table public.holdings enable row level security;
alter table public.reports  enable row level security;

-- holdings: you can only see and change your own rows.
-- (An UPDATE needs a SELECT policy too, and WITH CHECK stops a row being reassigned to someone else.)
drop policy if exists "holdings_select_own" on public.holdings;
drop policy if exists "holdings_insert_own" on public.holdings;
drop policy if exists "holdings_update_own" on public.holdings;
drop policy if exists "holdings_delete_own" on public.holdings;

create policy "holdings_select_own" on public.holdings
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "holdings_insert_own" on public.holdings
  for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "holdings_update_own" on public.holdings
  for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "holdings_delete_own" on public.holdings
  for delete to authenticated using ((select auth.uid()) = user_id);

-- reports: same rules.
drop policy if exists "reports_select_own" on public.reports;
drop policy if exists "reports_insert_own" on public.reports;
drop policy if exists "reports_update_own" on public.reports;
drop policy if exists "reports_delete_own" on public.reports;

create policy "reports_select_own" on public.reports
  for select to authenticated using ((select auth.uid()) = user_id);
create policy "reports_insert_own" on public.reports
  for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "reports_update_own" on public.reports
  for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "reports_delete_own" on public.reports
  for delete to authenticated using ((select auth.uid()) = user_id);

-- ---------------------------------------------------------------------------------------------- grants
-- Supabase no longer exposes new tables to the Data API automatically, so access is granted explicitly,
-- and only to signed-in users. `anon` (not signed in) gets nothing.
revoke all on public.holdings from anon, authenticated;
revoke all on public.reports  from anon, authenticated;

grant select, insert, update, delete on public.holdings to authenticated;
grant select, insert, update, delete on public.reports  to authenticated;
