import json

import pytest

from backend.app import ai, config

HEADLINES = [
    {"id": "N1", "title": "ABB India logs record orders", "outlet": "Mint", "date": "21 Nov"},
    {"id": "N2", "title": "Sensex ends lower; ABB among losers", "outlet": "Reuters", "date": "20 Nov"},
    {"id": "N3", "title": "SEBI order against ABB India auditor", "outlet": "Moneycontrol", "date": "18 Nov"},
]


class FakeLLM:
    """Replays scripted responses and records every call."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def complete_json(self, model, system, user):
        self.calls.append((model, system, user))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r)


@pytest.fixture(autouse=True)
def models(monkeypatch):
    monkeypatch.setattr(config, "LABELLER_MODEL", "small-model")
    monkeypatch.setattr(config, "WRITER_MODEL", "big-model")


def label(id, about="yes", tone="neutral", serious="no", summary="Something happened."):
    return {"id": id, "about_company": about, "tone": tone, "serious": serious, "summary": summary}


GOOD_LABELS = {"labels": [label("N1", tone="good", summary="Orders hit a record."),
                          label("N2", about="no"),
                          label("N3", tone="bad", serious="yes", summary="A regulator issued an order.")]}


# ------------------------------------------------------------------ labeller
def test_labeller_returns_labels_and_sends_the_small_model_the_untrusted_warning():
    llm = FakeLLM(GOOD_LABELS)
    out = ai.label_headlines(llm, "ABB India Limited", HEADLINES)
    assert out["N1"].tone == "good" and out["N1"].about_company is True
    assert out["N2"].about_company is False
    assert out["N3"].serious is True
    model, system, user = llm.calls[0]
    assert model == "small-model" and "untrusted" in system
    assert json.loads(user)["company"] == "ABB India Limited"


def test_labels_convert_to_news_labels_for_scoring():
    out = ai.label_headlines(FakeLLM(GOOD_LABELS), "ABB", HEADLINES)
    nl = out["N3"].as_news_label()
    assert (nl.about_company, nl.tone, nl.serious) == (True, "bad", True)


@pytest.mark.parametrize("bad", [
    "not json", "[]", {"labels": "x"},
    {"labels": [label("N1"), label("N2")]},                                  # missing N3
    {"labels": [label("N1"), label("N1"), label("N2"), label("N3")]},        # duplicate id
    {"labels": [label("N1"), label("N2"), label("N9")]},                     # unknown id
    {"labels": [label("N1", tone="ecstatic"), label("N2"), label("N3")]},    # bad tone
    {"labels": [label("N1", about="maybe"), label("N2"), label("N3")]},      # bad yes/no
    {"labels": [label("N1", summary=""), label("N2"), label("N3")]},         # empty summary
])
def test_labeller_rejects_malformed_output_then_retries_once(bad):
    llm = FakeLLM(bad, GOOD_LABELS)
    assert ai.label_headlines(llm, "ABB", HEADLINES) is not None
    assert len(llm.calls) == 2


def test_labeller_gives_up_after_two_bad_responses_and_on_provider_errors():
    assert ai.label_headlines(FakeLLM("nope", "nope"), "ABB", HEADLINES) is None
    assert ai.label_headlines(FakeLLM(ai.AiUnavailable("down")), "ABB", HEADLINES) is None
    assert ai.label_headlines(None, "ABB", HEADLINES) is None


def test_labeller_with_no_headlines_makes_no_call():
    llm = FakeLLM()
    assert ai.label_headlines(llm, "ABB", []) == {}
    assert llm.calls == []


def test_labeller_accepts_boolean_yes_no_values():
    resp = {"labels": [label("N1", about=True, serious=False), label("N2", about="No"), label("N3", serious="YES")]}
    out = ai.label_headlines(FakeLLM(resp), "ABB", HEADLINES)
    assert out["N1"].about_company is True and out["N3"].serious is True


def test_pick_top_news_puts_serious_then_bad_first_and_skips_unrelated():
    labels = ai.validate_labels(json.dumps(GOOD_LABELS), ["N1", "N2", "N3"])
    picked = ai.pick_top_news(HEADLINES, labels, n=3)
    assert [h["id"] for h in picked] == ["N3", "N1"]
    assert [h["id"] for h in ai.pick_top_news(HEADLINES, labels, n=1)] == ["N3"]


# ------------------------------------------------------------------ banned words
@pytest.mark.parametrize("text,banned", [
    ("You should buy this stock", True), ("Analysts set a target of 100", True), ("They recommend it", True),
    ("Selling pressure", True), ("A Recommended pick", True),
    ("The company announced a buyback", False), ("Sales rose 19%", False), ("Targeting new markets" , False),
])
def test_banned_words(text, banned):
    assert ai.has_banned_word(text) is banned


# ------------------------------------------------------------------ writer
FACTS = [
    {"id": "F1", "label": "Sales, last 4 quarters vs the 4 before", "value": "+19.0%", "as_of": "Sep 2026 quarter"},
    {"id": "F2", "label": "Return on capital (ROCE)", "value": "29.9%", "as_of": "Latest year"},
    {"id": "F3", "label": "P/E", "value": "94.8", "as_of": "Latest"},
    {"id": "F4", "label": "Company description", "value": "ABB India makes electrical and automation equipment.", "as_of": ""},
]
NEWS = [{"id": "N1", "title": "ABB India logs record orders", "date": "21 Nov", "summary": "Orders hit a record."}]
QUESTIONS = [{"question": "Is the business growing?", "status": "green", "value": "Sales up 19.0%"}]

GOOD_TEXT = {
    "overall": {"text": "Sales grew about 19% over the last year [F1]. The business earns a high return on capital [F2].",
                "cites": ["F1", "F2"]},
    "about": {"text": "ABB India makes electrical and automation equipment [F4].", "cites": ["F4"]},
}


def write(*responses):
    llm = FakeLLM(*responses)
    return ai.write_report_text(llm, "ABB India Limited", FACTS, NEWS, QUESTIONS, "Looks solid"), llm


def test_writer_accepts_a_clean_cited_response():
    out, llm = write(GOOD_TEXT)
    assert out["overall"]["cites"] == ["F1", "F2"] and out["about"]["text"].startswith("ABB India makes")
    model, system, user = llm.calls[0]
    assert model == "big-model" and "Never give investment advice" in system
    assert json.loads(user)["overall_label"] == "Looks solid"


def with_overall(text, cites):
    return {**GOOD_TEXT, "overall": {"text": text, "cites": cites}}


@pytest.mark.parametrize("bad,reason_hint", [
    (with_overall("Sales grew 19% [F1]. You should buy it [F2].", ["F1", "F2"]), "banned word"),
    (with_overall("Sales grew 19% [F1]. It earns well.", ["F1"]), "uncited sentence"),
    (with_overall("Sales grew 19% [F7].", ["F7"]), "unknown id"),
    (with_overall("Sales grew 19% [F1].", ["F2"]), "cites list mismatch"),
    (with_overall("Sales grew 19% [F1].", []), "no cites"),
    (with_overall("Sales grew 47% [F1].", ["F1"]), "invented number"),
    (with_overall("Sales grew 19% [N5].", ["N5"]), "unknown news id"),
    ({"overall": GOOD_TEXT["overall"]}, "missing about"),
    ("not json", "invalid json"),
    ([], "wrong shape"),
])
def test_writer_rejects_bad_output_and_retries_once(bad, reason_hint):
    out, llm = write(bad, GOOD_TEXT)
    assert out is not None, reason_hint
    assert len(llm.calls) == 2


def test_writer_returns_none_after_two_failures_and_when_unavailable():
    bad = with_overall("Sales grew 19% [F1]. You should buy it [F2].", ["F1", "F2"])
    out, llm = write(bad, bad)
    assert out is None and len(llm.calls) == 2
    assert ai.write_report_text(FakeLLM(ai.AiUnavailable("x")), "ABB", FACTS, NEWS, QUESTIONS, "Mixed") is None
    assert ai.write_report_text(None, "ABB", FACTS, NEWS, QUESTIONS, "Mixed") is None


def test_numbers_may_be_rounded_versions_of_fact_values_but_not_invented():
    ok = with_overall("Sales grew 19% [F1]. The return on capital is 29.9% [F2].", ["F1", "F2"])
    assert write(ok)[0] is not None
    rounded = with_overall("The return on capital is about 30% [F2].", ["F2"])
    assert write(rounded)[0] is not None               # 29.9 rounds to 30
    off = with_overall("The return on capital is 35% [F2].", ["F2"])
    assert write(off, off)[0] is None


def test_citation_markers_do_not_count_as_numbers_and_ids_with_digits_are_fine():
    ok = {"overall": {"text": "The share price is high against its profit [F3].", "cites": ["F3"]}, "about": GOOD_TEXT["about"]}
    assert write(ok)[0] is not None


def test_check_passage_reports_reasons():
    ids = {"F1", "F2"}
    assert ai.check_passage({"text": "Sales rose [F1].", "cites": ["F1"]}, ids, "") is None
    assert ai.check_passage({"text": "Sales rose.", "cites": ["F1"]}, ids, "") == "cites do not match the markers in the text"
    assert ai.check_passage({"text": "Sales rose [F1]. And more", "cites": ["F1"]}, ids, "") == "a sentence has no citation"
    assert ai.check_passage("x", ids, "") == "not an object"
    assert ai.check_passage({"text": " ", "cites": ["F1"]}, ids, "") == "empty text"


# ------------------------------------------------------------------ provider wiring
def test_get_llm_needs_key_and_both_models(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    assert ai.get_llm() is None
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(config, "WRITER_MODEL", "")
    assert ai.get_llm() is None


def test_missing_model_name_disables_the_call(monkeypatch):
    monkeypatch.setattr(config, "LABELLER_MODEL", "")
    assert ai.label_headlines(FakeLLM(GOOD_LABELS), "ABB", HEADLINES) is None
