import pytest

from backend.app import ai, flags


def rep(label="mixed", greys=(), news=None, news_ok=True, price=100.0):
    display = {"looks_solid": "Looks solid", "mixed": "Mixed", "be_careful": "Be careful"}[label]
    ids = ["growth", "efficiency", "debt", "price", "news"]
    return {
        "label": {"code": label, "display": display},
        "questions": [{"id": i, "status": "grey" if i in greys else "green"} for i in ids],
        "news": news or [],
        "sources": [{"name": "Google News", "ok": news_ok}],
        "price": {"value": price},
    }


def item(url, serious=False):
    return {"title": url, "url": url, "serious": serious}


def run(latest, previous=None, *, price=100.0, buy=100.0, watching=False):
    return flags.evaluate(watching=watching, buy_price=buy, price=price, latest=latest, previous=previous)


def codes(reasons):
    return [r["code"] for r in reasons]


# ------------------------------------------------------------------ be_careful
def test_be_careful_fires_on_the_label_alone():
    r = run(rep("be_careful"))
    assert codes(r) == ["be_careful"] and r[0]["text"] == "Label is Be careful"


@pytest.mark.parametrize("label", ["looks_solid", "mixed"])
def test_other_labels_do_not_flag(label):
    assert run(rep(label)) == []


# ------------------------------------------------------------------ label_worse
@pytest.mark.parametrize("old,new", [("looks_solid", "mixed"), ("mixed", "be_careful"), ("looks_solid", "be_careful")])
def test_label_worse_fires_for_every_downgrade(old, new):
    r = run(rep(new), rep(old))
    assert "label_worse" in codes(r)
    text = next(x["text"] for x in r if x["code"] == "label_worse")
    assert text == f"Label went from {rep(old)['label']['display']} to {rep(new)['label']['display']}"


@pytest.mark.parametrize("old,new", [("mixed", "mixed"), ("mixed", "looks_solid"), ("be_careful", "mixed"),
                                     ("be_careful", "be_careful")])
def test_label_same_or_better_does_not_fire(old, new):
    assert "label_worse" not in codes(run(rep(new), rep(old)))


def test_label_worse_needs_a_previous_report():
    assert "label_worse" not in codes(run(rep("be_careful"), None))


def test_outage_guard_ignores_a_label_drop_caused_by_a_newly_grey_question():
    previous = rep("looks_solid")
    latest = rep("mixed", greys=("news",))        # AI was down: news went grey and the label slipped
    assert "label_worse" not in codes(run(latest, previous))


def test_outage_guard_does_not_hide_a_real_drop_when_greys_were_already_there():
    previous = rep("looks_solid", greys=("news",))
    latest = rep("mixed", greys=("news",))
    assert "label_worse" in codes(run(latest, previous))


def test_a_question_recovering_from_grey_does_not_block_the_rule():
    previous = rep("looks_solid", greys=("news",))
    latest = rep("mixed")
    assert "label_worse" in codes(run(latest, previous))


def test_unknown_label_codes_never_fire():
    latest, previous = rep("mixed"), rep("looks_solid")
    latest["label"]["code"] = "something_new"
    assert "label_worse" not in codes(run(latest, previous))


# ------------------------------------------------------------------ price_drop
@pytest.mark.parametrize("price,fires", [(80.0, True), (79.99, True), (80.01, False), (100.0, False), (150.0, False)])
def test_price_drop_boundary_at_exactly_20_percent(price, fires):
    assert ("price_drop" in codes(run(rep("looks_solid"), price=price, buy=100.0))) is fires


def test_price_drop_text_rounds_down():
    r = run(rep("looks_solid"), price=76.4, buy=100.0)      # 23.6% below
    assert next(x["text"] for x in r if x["code"] == "price_drop") == "Price is 23% below what you paid"
    r = run(rep("looks_solid"), price=80.0, buy=100.0)
    assert next(x["text"] for x in r if x["code"] == "price_drop") == "Price is 20% below what you paid"


def test_price_drop_skipped_for_watching_and_unknown_prices():
    assert run(rep("looks_solid"), price=10, buy=100, watching=True) == []
    assert run(rep("looks_solid"), price=None, buy=100) == []
    assert run(rep("looks_solid"), price=10, buy=None) == []
    assert run(rep("looks_solid"), price=10, buy=0) == []


# ------------------------------------------------------------------ serious_news
def test_serious_news_fires_for_an_unseen_serious_url():
    previous = rep("mixed", news=[item("https://a")])
    latest = rep("mixed", news=[item("https://a"), item("https://b", serious=True)])
    r = run(latest, previous)
    assert codes(r) == ["serious_news"] and r[0]["text"] == "New serious news since the last refresh"


def test_serious_news_does_not_fire_for_a_url_already_seen():
    previous = rep("mixed", news=[item("https://b", serious=True)])
    latest = rep("mixed", news=[item("https://b", serious=True)])
    assert run(latest, previous) == []


def test_non_serious_new_news_does_not_fire():
    previous = rep("mixed", news=[item("https://a")])
    latest = rep("mixed", news=[item("https://c", serious=False)])
    assert run(latest, previous) == []


def test_serious_news_needs_previous_report_and_a_working_previous_news_source():
    latest = rep("mixed", news=[item("https://b", serious=True)])
    assert run(latest, None) == []
    assert run(latest, rep("mixed", news_ok=False)) == []        # news was down before: everything would look "new"
    no_source = rep("mixed")
    no_source["sources"] = []
    assert run(latest, no_source) == []


def test_old_reports_without_the_serious_field_never_fire():
    previous = rep("mixed", news=[{"title": "x", "url": "https://a"}])
    latest = rep("mixed", news=[{"title": "y", "url": "https://b"}])       # cached before Phase 2: no "serious" key
    assert run(latest, previous) == []


# ------------------------------------------------------------------ combined behaviour
def test_reasons_come_in_the_documented_order_and_join_with_semicolons():
    previous = rep("looks_solid", news=[item("https://a")])
    latest = rep("be_careful", news=[item("https://b", serious=True)])
    r = run(latest, previous, price=70, buy=100)
    assert codes(r) == ["be_careful", "label_worse", "price_drop", "serious_news"]
    block = flags.flag_block(r)
    assert block["on"] is True and len(block["reasons"]) == 4
    assert block["reason"] == "; ".join(x["text"] for x in r)


def test_watching_stocks_use_the_three_non_price_rules():
    previous = rep("looks_solid", news=[item("https://a")])
    latest = rep("be_careful", news=[item("https://b", serious=True)])
    assert codes(run(latest, previous, price=1, buy=None, watching=True)) == ["be_careful", "label_worse", "serious_news"]


def test_no_report_means_no_flag_whatever_the_price():
    assert run(None, None, price=1, buy=100) == []
    assert flags.flag_block([]) == {"on": False, "reasons": [], "reason": ""}


def test_flag_texts_never_contain_advice_words():
    previous = rep("looks_solid", news=[item("https://a")])
    latest = rep("be_careful", news=[item("https://b", serious=True)])
    for r in run(latest, previous, price=50, buy=100):
        assert not ai.has_banned_word(r["text"]), r["text"]


# ------------------------------------------------------------------ report-derived codes (used for "new flags")
def test_report_codes_use_the_price_stored_in_the_report():
    latest = rep("looks_solid", price=70.0)
    assert flags.report_codes(watching=False, buy_price=100.0, latest=latest, previous=None) == {"price_drop"}
    assert flags.report_codes(watching=False, buy_price=100.0, latest=rep("looks_solid", price=95.0), previous=None) == set()


def test_report_codes_cope_with_reports_cached_before_price_value_existed():
    latest = rep("looks_solid")
    del latest["price"]["value"]
    assert flags.report_codes(watching=False, buy_price=100.0, latest=latest, previous=None) == set()
    assert flags.report_price(None) is None and flags.report_price({"price": {"value": "x"}}) is None
