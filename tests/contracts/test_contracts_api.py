"""msa.contracts.api: RunRequest defaults, the Event discriminated union, and Violation."""

import pytest
from pydantic import ValidationError

from msa.contracts.api import RunRequest, Violation


def test_run_request_minimal_defaults():
    r = RunRequest(portfolio_id="PF1", event={"kind": "text", "text": "event text"})
    assert r.workflow_id == "stress_test"
    assert r.seed == 20260911
    assert r.mc_points == 8192
    assert r.request_graph_review is False
    assert r.auto_approve is False
    assert r.models == {}
    assert r.agents == []


def test_run_request_event_discriminates_on_kind():
    text = RunRequest(portfolio_id="PF1", event={"kind": "text", "text": "t"})
    url = RunRequest(portfolio_id="PF1", event={"kind": "url", "url": "https://example.com/a"})
    doc = RunRequest(portfolio_id="PF1", event={"kind": "doc_id", "doc_id": "doc:1"})
    library = RunRequest(portfolio_id="PF1", event={"kind": "library", "id": "evt:1"})
    assert text.event.kind == "text"
    assert str(url.event.url).startswith("https://example.com")
    assert doc.event.doc_id == "doc:1"
    assert library.event.id == "evt:1"


def test_run_request_rejects_unknown_event_kind():
    with pytest.raises(ValidationError):
        RunRequest(portfolio_id="PF1", event={"kind": "video", "url": "https://example.com"})


def test_run_request_mc_points_only_accepts_declared_values():
    with pytest.raises(ValidationError):
        RunRequest(portfolio_id="PF1", event={"kind": "text", "text": "t"}, mc_points=1000)


def test_run_request_strict_bool_rejects_truthy_non_bool():
    with pytest.raises(ValidationError):
        RunRequest(
            portfolio_id="PF1",
            event={"kind": "text", "text": "t"},
            auto_approve=1,
        )


def test_run_request_scenario_words_reject_blank_string():
    with pytest.raises(ValidationError):
        RunRequest(portfolio_id="PF1", event={"kind": "text", "text": "t"}, scenario="   ")


def test_violation_rule_id_pattern_accepts_v_numbers_and_scenario():
    v1 = Violation(rule_id="V1", path="", message="m")
    v11 = Violation(rule_id="V11", path="/a/b", message="m")
    scenario = Violation(rule_id="SCENARIO", path="", message="m")
    assert v1.rule_id == "V1"
    assert v11.rule_id == "V11"
    assert scenario.rule_id == "SCENARIO"


def test_violation_rejects_rule_id_out_of_range():
    with pytest.raises(ValidationError):
        Violation(rule_id="V12", path="", message="m")
    with pytest.raises(ValidationError):
        Violation(rule_id="V0", path="", message="m")
