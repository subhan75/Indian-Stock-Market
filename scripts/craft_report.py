"""Test helper: make a stock's stored reports look like a change happened, so the two flag rules that
depend on *change over time* can be tried by hand.

    set DB_PATH to a THROWAWAY database first (the script refuses to run without it), then:

    python scripts/craft_report.py label-worse    TITAN   # adds a copy, one second older, labelled "Looks solid"
    python scripts/craft_report.py serious-news   ABB     # adds a NEWER copy with one unseen serious headline
    python scripts/craft_report.py show           ABB     # prints the stored reports, newest first

The stock must already have a report (add it in My stocks first). Then reload My stocks.
"""
import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DISPLAY = {"looks_solid": "Looks solid", "mixed": "Mixed", "be_careful": "Be careful"}


def fail(message: str) -> None:
    print(f"Error: {message}")
    raise SystemExit(1)


def main(argv: list[str]) -> None:
    if not os.environ.get("DB_PATH"):
        fail("DB_PATH is not set. This script changes stored reports, so it only runs against a throwaway "
             "database. Set DB_PATH to a temp file first (see the testing guide).")
    if len(argv) != 3 or argv[1] not in {"label-worse", "serious-news", "show"}:
        fail(__doc__.strip())
    action, symbol = argv[1], argv[2].upper()

    from backend.app import report  # imported late so DB_PATH is already in the environment

    found = report.recent_reports(symbol, 5)
    if not found:
        fail(f"{symbol} has no stored report. Add it in My stocks (or open its report) first.")
    latest = found[0]

    if action == "show":
        for r in found:
            news = [(n.get("title", "")[:40], n.get("serious")) for n in r.get("news", [])]
            print(r["generated_at"], r["label"]["display"], "| news:", news)
        return

    stamp = datetime.fromisoformat(latest["generated_at"])
    if action == "label-worse":
        if latest["label"]["code"] == "looks_solid":
            fail(f"{symbol}'s latest label is already 'Looks solid', so nothing can get worse. "
                 "Try a stock labelled Mixed or Be careful (TITAN usually is).")
        older = deepcopy(latest)
        # The flag compares the two NEWEST reports, so the copy must sit just below the latest one.
        older["generated_at"] = (stamp - timedelta(seconds=1)).isoformat(timespec="seconds")
        older["label"] = {"code": "looks_solid", "display": DISPLAY["looks_solid"]}
        older["questions"] = [{**q, "status": q["status"] if q["status"] != "grey" else "green"}
                              for q in older["questions"]]          # no newly-grey question, so the rule can fire
        report._save(older)
        print(f"Added an older {symbol} report labelled 'Looks solid'. Reload My stocks: expect "
              f"'Label went from Looks solid to {latest['label']['display']}'.")
        return

    newer = deepcopy(latest)
    newer["generated_at"] = (stamp + timedelta(minutes=1)).isoformat(timespec="seconds")
    newer["news"] = list(newer.get("news", [])) + [{
        "id": "N9", "title": "Regulator issues order against the company (crafted test headline)", "outlet": "Mint",
        "date_display": "25 Nov", "summary": "A crafted serious headline for testing.", "tone": "bad",
        "serious": True, "url": "https://example.com/crafted-serious-headline"}]
    older_sources = [s for s in latest.get("sources", []) if s.get("name") != "Google News"]
    latest_sources = older_sources + [{"name": "Google News", "ok": True, "fetched_at_display": ""}]
    newer["sources"] = latest_sources
    report._save(newer)
    print(f"Added a newer {symbol} report with one unseen serious headline. Reload My stocks: expect "
          "'New serious news since the last refresh' (needs the earlier report's news source to have worked).")


if __name__ == "__main__":
    main(sys.argv)
