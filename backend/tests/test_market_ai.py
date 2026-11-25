import json

import pytest

from backend.app import ai, config

INDICES = [{"name": "Nifty 50", "level": 25819, "change_percent": 1.79},
           {"name": "Sensex", "level": 83938, "change_percent": 1.83}]
HEADLINES = [
    {"id": "H1", "title": "Sensex jumps 1,500 points as banks rally", "outlet": "ET Markets", "time": "7:19 pm", "description": ""},
    {"id": "H2", "title": "US stocks slide as AI costs worry investors", "outlet": "Business Standard", "time": "6:37 pm",
     "description": "AI-linked stocks fell as investors reassessed the rising cost of infrastructure."},
    {"id": "H3", "title": "RBI net buyer of dollars for fourth month", "outlet": "ET Markets", "time": "6:49 pm", "description": ""},
]


class FakeLLM:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def complete_json(self, model, system, user):
        self.calls.append((model, system, user))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r)


@pytest.fixture(autouse=True)
def writer_model(monkeypatch):
    monkeypatch.setattr(config, "WRITER_MODEL", "big-model")


def pt(text, cites):
    return {"text": text, "cites": cites}


GOOD = {"points": [pt("Indian shares rose sharply as banks rallied [H1].", ["H1"]),
                   pt("US stocks fell on worries about AI costs [H2]. The RBI bought dollars again [H3].", ["H2", "H3"])]}


def write(*responses, headlines=HEADLINES, indices=INDICES):
    llm = FakeLLM(*responses)
    return ai.write_market_points(llm, indices, headlines), llm


# ------------------------------------------------------------------ the happy path
def test_clean_points_pass_and_the_prompt_carries_the_safety_rules():
    out, llm = write(GOOD)
    assert out == GOOD["points"]
    model, system, user = llm.calls[0]
    assert model == "big-model" and "untrusted" in system and "do not guess a cause" in system
    payload = json.loads(user)
    assert [h["id"] for h in payload["headlines"]] == ["H1", "H2", "H3"] and payload["indices"][0]["name"] == "Nifty 50"


def test_exactly_three_points_are_allowed_and_cites_may_reference_any_shown_headline():
    three = {"points": [pt("One [H1].", ["H1"]), pt("Two [H2].", ["H2"]), pt("Three [H3].", ["H3"])]}
    assert len(write(three)[0]) == 3


def test_numbers_may_come_from_headlines_index_figures_or_rounding():
    ok = {"points": [pt("The Sensex gained about 1,500 points [H1].", ["H1"]),
                     pt("Nifty 50 was up about 1.8% [H1].", ["H1"])]}
    assert write(ok)[0] is not None
    assert write({"points": [pt("Nifty 50 closed near 25,819 [H1].", ["H1"])]})[0] is not None


# ------------------------------------------------------------------ every bad case is rejected, then retried once
BAD = [
    ("invalid json", "not json"),
    ("not an object", []),
    ("no points key", {"summary": "x"}),
    ("empty points", {"points": []}),
    ("points not a list", {"points": "x"}),
    ("unknown cite", {"points": [pt("Markets rose [H9].", ["H9"])]}),
    ("cite list mismatch", {"points": [pt("Markets rose [H1].", ["H2"])]}),
    ("uncited sentence", {"points": [pt("Markets rose [H1]. Banks led the move.", ["H1"])]}),
    ("no cites", {"points": [pt("Markets rose [H1].", [])]}),
    ("banned word buy", {"points": [pt("Investors should buy banks [H1].", ["H1"])]}),
    ("banned word target", {"points": [pt("The index hit its target [H1].", ["H1"])]}),
    ("banned word recommend", {"points": [pt("Analysts recommend caution [H1].", ["H1"])]}),
    ("invented number", {"points": [pt("The Sensex gained 4,700 points [H1].", ["H1"])]}),
    ("invented percentage", {"points": [pt("Banks rose 12.5% [H1].", ["H1"])]}),
    ("more than three points", {"points": [pt(f"Point {i} [H1].", ["H1"]) for i in range(4)]}),
    ("a point that is not an object", {"points": ["just text"]}),
]


@pytest.mark.parametrize("label,bad", BAD, ids=[b[0] for b in BAD])
def test_bad_output_is_rejected_then_retried_once(label, bad):
    out, llm = write(bad, GOOD)
    assert out == GOOD["points"], label
    assert len(llm.calls) == 2


def test_two_bad_responses_give_none():
    out, llm = write("nope", {"points": [pt("Buy now [H1].", ["H1"])]})
    assert out is None and len(llm.calls) == 2


# ------------------------------------------------------------------ partial results, outages, no input
def test_a_failing_point_is_dropped_and_the_good_ones_kept_without_a_retry():
    mixed = {"points": [pt("Indian shares rose [H1].", ["H1"]), pt("You should buy banks [H1].", ["H1"])]}
    out, llm = write(mixed)
    assert out == [pt("Indian shares rose [H1].", ["H1"])] and len(llm.calls) == 1


def test_text_is_stripped_of_surrounding_whitespace():
    out, _ = write({"points": [pt("  Shares rose [H1].  ", ["H1"])]})
    assert out[0]["text"] == "Shares rose [H1]."


def test_no_headlines_means_no_call_and_no_points():
    out, llm = write(headlines=[])
    assert out is None and llm.calls == []


def test_no_llm_or_no_model_means_none():
    assert ai.write_market_points(None, INDICES, HEADLINES) is None
    config.WRITER_MODEL = ""
    assert ai.write_market_points(FakeLLM(GOOD), INDICES, HEADLINES) is None


def test_provider_error_gives_none_without_raising():
    out, llm = write(ai.AiUnavailable("down"))
    assert out is None and len(llm.calls) == 1


def test_works_with_no_index_figures():
    out, _ = write({"points": [pt("Shares rose [H1].", ["H1"])]}, indices=[])
    assert out is not None


def test_citation_markers_with_h_ids_are_recognised_by_the_shared_checker():
    assert ai.check_passage(pt("Shares rose [H1].", ["H1"]), {"H1"}, "") is None
    assert ai.check_passage(pt("Shares rose [H2].", ["H2"]), {"H1"}, "") == "cites an id that does not exist"
    assert ai.check_passage(pt("Shares rose.", ["H1"]), {"H1"}, "") == "cites do not match the markers in the text"


def test_rejections_are_logged_with_the_reason(caplog):
    import logging

    caplog.set_level(logging.WARNING, logger="stock_analyst.ai")
    write({"points": [pt("Investors should buy banks [H1].", ["H1"])]}, GOOD)
    assert any("Market summary" in r.getMessage() and "banned word" in r.getMessage() for r in caplog.records)
