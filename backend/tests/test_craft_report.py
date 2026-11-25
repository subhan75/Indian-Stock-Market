import importlib.util
from pathlib import Path

import pytest

from backend.app import flags
from backend.app.store import InMemoryStore

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "craft_report.py"
spec = importlib.util.spec_from_file_location("craft_report", SCRIPT)
craft = importlib.util.module_from_spec(spec)
spec.loader.exec_module(craft)


def report(label="mixed", when="2026-11-25T10:00:00+05:30", greys=()):
    return {"symbol": "TITAN", "generated_at": when,
            "label": {"code": label, "display": {"looks_solid": "Looks solid", "mixed": "Mixed", "be_careful": "Be careful"}[label]},
            "questions": [{"id": i, "status": "grey" if i in greys else "green"} for i in ("growth", "efficiency", "debt", "price", "news")],
            "news": [{"id": "N1", "title": "Orders rise", "url": "https://n/1", "serious": False}],
            "sources": [{"name": "Google News", "ok": True}], "price": {"value": 100.0}}


def reasons(store):
    found = store.reports_recent("TITAN", 2)
    previous = found[1] if len(found) > 1 else None
    return [r["code"] for r in flags.evaluate(watching=True, buy_price=None, price=None, latest=found[0], previous=previous)]


def test_label_worse_makes_the_flag_fire_even_with_a_real_older_report_in_the_history():
    s = InMemoryStore()
    s.reports_save(report("looks_solid", "2026-11-20T10:00:00+05:30"))
    s.reports_save(report("mixed", "2026-11-25T10:00:00+05:30"))
    craft.label_worse(s, "TITAN")
    assert "label_worse" in reasons(s)


def test_serious_news_makes_the_flag_fire():
    s = InMemoryStore()
    s.reports_save(report("looks_solid"))
    craft.serious_news(s, "TITAN")
    assert reasons(s) == ["serious_news"]


def test_label_worse_ignores_an_outage_style_grey_question_so_the_rule_can_fire():
    s = InMemoryStore()
    s.reports_save(report("mixed", greys=("news",)))
    craft.label_worse(s, "TITAN")
    assert "label_worse" in reasons(s)


def test_sensible_refusals():
    s = InMemoryStore()
    with pytest.raises(craft.CraftError, match="no stored report"):
        craft.label_worse(s, "TITAN")
    with pytest.raises(craft.CraftError, match="no stored report"):
        craft.serious_news(s, "TITAN")
    s.reports_save(report("looks_solid"))
    with pytest.raises(craft.CraftError, match="already 'Looks solid'"):
        craft.label_worse(s, "TITAN")


def test_show_lists_newest_first():
    s = InMemoryStore()
    s.reports_save(report("mixed", "2026-11-20T10:00:00+05:30"))
    s.reports_save(report("looks_solid", "2026-11-25T10:00:00+05:30"))
    lines = craft.show(s, "TITAN")
    assert lines[0].startswith("2026-11-25") and lines[1].startswith("2026-11-20")
