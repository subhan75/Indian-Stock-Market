import json
import logging

import pytest

from backend.app import ai, config, report

LOGGER = "stock_analyst.ai"
HEADLINES = [{"id": "N1", "title": "ABB India logs record orders", "outlet": "Mint", "date": "21 Nov"}]
FACTS = [{"id": "F1", "label": "Sales", "value": "+19.0%", "as_of": "Q"}]


class Raises:
    def __init__(self, exc):
        self.exc = exc

    def complete_json(self, model, system, user):
        raise self.exc


class Returns:
    def __init__(self, *outputs):
        self.outputs = list(outputs)

    def complete_json(self, model, system, user):
        return self.outputs.pop(0)


@pytest.fixture(autouse=True)
def models(monkeypatch):
    monkeypatch.setattr(config, "LABELLER_MODEL", "small")
    monkeypatch.setattr(config, "WRITER_MODEL", "big")


def messages(caplog):
    return [r.getMessage() for r in caplog.records if r.name == LOGGER]


def test_not_configured_is_logged_for_both_calls(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    assert ai.label_headlines(None, "ABB", HEADLINES) is None
    assert ai.write_report_text(None, "ABB", FACTS, [], [], "Mixed") is None
    text = " ".join(messages(caplog))
    assert "LABELLER_MODEL" in text and "WRITER_MODEL" in text


def test_provider_errors_are_logged_without_the_api_key(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    leak = "Incorrect API key provided: sk-proj-ABCDEF1234567890secret. You can find your key at ..."
    ai.label_headlines(Raises(ai.AiUnavailable(leak)), "ABB", HEADLINES)
    ai.write_report_text(Raises(ai.AiUnavailable(leak)), "ABB", FACTS, [], [], "Mixed")
    joined = " ".join(messages(caplog))
    assert "provider error" in joined and "Incorrect API key" in joined
    assert "ABCDEF1234567890secret" not in joined and "sk-***" in joined


def test_labeller_rejection_is_logged_for_each_attempt(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    assert ai.label_headlines(Returns("nope", "nope"), "ABB", HEADLINES) is None
    assert sum("rejected" in m for m in messages(caplog)) == 2


def test_writer_rejection_says_which_passage_and_why(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    bad = json.dumps({"overall": {"text": "You should buy it [F1].", "cites": ["F1"]},
                      "about": {"text": "Makes things [F9].", "cites": ["F9"]}})
    assert ai.write_report_text(Returns(bad, "not json"), "ABB", FACTS, [], [], "Mixed") is None
    msgs = messages(caplog)
    assert len(msgs) == 2
    assert "overall: banned word" in msgs[0] and "about: cites an id that does not exist" in msgs[0]
    assert "wasn't a JSON object" in msgs[1]


def test_safe_text_redacts_and_truncates():
    assert ai.safe_text("key sk-abc123456789 bad") == "key sk-*** bad"
    assert len(ai.safe_text("x" * 1000)) == 300
