"""Test helper: make a stock's stored reports look like a change happened, so the two "Look at this" rules that
depend on CHANGE OVER TIME (label got worse, new serious news) can be tried by hand.

It signs in as a Supabase account and edits THAT account's reports (through Row Level Security, like the app does).
Use a separate TEST account, never your real one: it adds invented report copies to that account's history.

    set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY (PowerShell: $env:SUPABASE_URL = "...")
    python scripts/craft_report.py label-worse   TITAN --email test@example.com   # a copy, 1 s older, "Looks solid"
    python scripts/craft_report.py serious-news  ABB   --email test@example.com   # a newer copy with an unseen serious headline
    python scripts/craft_report.py show          ABB   --email test@example.com   # list stored reports, newest first

The password is asked for at a hidden prompt. The stock must already have a report (add it in My stocks first).
Then reload My stocks.
"""
import argparse
import getpass
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DISPLAY = {"looks_solid": "Looks solid", "mixed": "Mixed", "be_careful": "Be careful"}


class CraftError(Exception):
    pass


def show(store, symbol: str) -> list[str]:
    lines = []
    for r in store.reports_recent(symbol, 10):
        news = [(n.get("title", "")[:40], n.get("serious")) for n in r.get("news", [])]
        lines.append(f"{r['generated_at']} {r['label']['display']} | news: {news}")
    return lines


def label_worse(store, symbol: str) -> str:
    found = store.reports_recent(symbol, 1)
    if not found:
        raise CraftError(f"{symbol} has no stored report. Add it in My stocks (or open its report) first.")
    latest = found[0]
    if latest["label"]["code"] == "looks_solid":
        raise CraftError(f"{symbol}'s latest label is already 'Looks solid', so nothing can get worse. "
                         "Try a stock labelled Mixed or Be careful.")
    older = deepcopy(latest)
    # The flag compares the two NEWEST reports, so the copy must sit just below the latest one.
    older["generated_at"] = (datetime.fromisoformat(latest["generated_at"]) - timedelta(seconds=1)).isoformat(timespec="seconds")
    older["label"] = {"code": "looks_solid", "display": DISPLAY["looks_solid"]}
    # The copy keeps exactly the same grey rows as the latest report, so no question looks NEWLY grey (which the
    # outage guard would treat as missing data, not a real drop) and the rule can fire for any stock.
    store.reports_save(older)
    return f"Added an older {symbol} report labelled 'Looks solid'. Reload My stocks: expect " \
           f"'Label went from Looks solid to {latest['label']['display']}'."


def serious_news(store, symbol: str) -> str:
    found = store.reports_recent(symbol, 1)
    if not found:
        raise CraftError(f"{symbol} has no stored report. Add it in My stocks (or open its report) first.")
    latest = found[0]
    newer = deepcopy(latest)
    newer["generated_at"] = (datetime.fromisoformat(latest["generated_at"]) + timedelta(minutes=1)).isoformat(timespec="seconds")
    newer["news"] = list(newer.get("news", [])) + [{
        "id": "N9", "title": "Regulator issues order against the company (crafted test headline)", "outlet": "Mint",
        "date_display": "25 Nov", "summary": "A crafted serious headline for testing.", "tone": "bad",
        "serious": True, "url": "https://example.com/crafted-serious-headline"}]
    newer["sources"] = [s for s in latest.get("sources", []) if s.get("name") != "Google News"] + \
        [{"name": "Google News", "ok": True, "fetched_at_display": ""}]
    store.reports_save(newer)
    return f"Added a newer {symbol} report with one unseen serious headline. Reload My stocks: expect " \
           "'New serious news since the last refresh' (needs the earlier report's news source to have worked)."


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=["label-worse", "serious-news", "show"])
    parser.add_argument("symbol")
    parser.add_argument("--email", required=True, help="the TEST account to edit")
    args = parser.parse_args(argv)

    from backend.app import auth, config
    from backend.app.store_supabase import SupabaseStore, make_client

    if not (config.SUPABASE_URL and config.SUPABASE_PUBLISHABLE_KEY):
        print("Set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY first.")
        return 1
    try:
        tokens = auth.sign_in(args.email.strip().lower(), getpass.getpass(f"Password for {args.email}: "))
    except auth.InvalidCredentials:
        print("Wrong email or password.")
        return 1
    store = SupabaseStore(make_client(tokens.access_token), tokens.user_id)
    symbol = args.symbol.strip().upper()
    try:
        if args.action == "show":
            print("\n".join(show(store, symbol)) or f"No reports stored for {symbol}.")
        else:
            print({"label-worse": label_worse, "serious-news": serious_news}[args.action](store, symbol))
    except CraftError as exc:
        print(f"Error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
