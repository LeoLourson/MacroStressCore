"""run_service.edited_by: a resumed magnitude the analyst changed is attributed to them."""

from datetime import date
from hashlib import sha256

from msa.contracts.causal_answer import ScenarioParameter
from msa.api.run_service import ANALYST_SCENARIO, edited_by
from msa.contracts.evidence import Evidence
from msa.platform.registry import registry
from tests.api.test_platform_api import client, get, post, wait  # noqa: F401

SHA = sha256(b"analyst-edits-test-fragment-1").hexdigest()
OTHER_SHA = sha256(b"analyst-edits-test-fragment-2").hexdigest()


def llm_evidence():
    return Evidence(
        kind="expert_assumption",
        source_id=SHA,
        locator="p1/para1/s1",
        fragment_sha256=SHA,
        author="LLM:m (оценка модели)",
        as_of=date(2026, 1, 1),
    )


def document_evidence():
    return Evidence(
        kind="document",
        source_id="event-doc",
        locator="p1/para2/s1",
        fragment_sha256=OTHER_SHA,
    )


def triangular(*, mode, label="channel_shock", evidence=None):
    return ScenarioParameter(
        label=label,
        kind="triangular",
        low=-0.2,
        mode=mode,
        high=0.0,
        unit="fraction",
        factor="equity.sector",
        channel="channel",
        evidence=[] if evidence is None else evidence,
    )


def point(*, value, label="direct_0", evidence=None):
    return ScenarioParameter(
        label=label,
        kind="point",
        value=value,
        unit="log_return",
        factor="equity.market",
        key="MOEX",
        evidence=[] if evidence is None else evidence,
    )


def test_llm_estimated_parameter_with_a_changed_mode_is_attributed_to_the_analyst():
    proposed = triangular(mode=-0.1, evidence=[llm_evidence()]).model_dump(mode="json")
    edited = triangular(mode=-0.05, evidence=[llm_evidence()])
    scenario = edited_by("analyst", {"channel_shock": proposed}, {"channel_shock": edited})
    evidence = scenario["channel_shock"]["evidence"]
    assert len(evidence) == 1
    assert evidence[0]["kind"] == "expert_assumption"
    assert evidence[0]["author"] == "analyst"
    assert evidence[0]["as_of"] == str(date.today())
    assert evidence[0]["locator"] == "p1/para1/s1"
    assert evidence[0]["fragment_sha256"] == SHA
    assert evidence[0]["source_id"] == SHA


def test_stated_parameter_with_a_changed_value_becomes_an_expert_assumption():
    proposed = point(value=0.1, evidence=[document_evidence()]).model_dump(mode="json")
    edited = point(value=0.12, evidence=[document_evidence()])
    scenario = edited_by("analyst", {"direct_0": proposed}, {"direct_0": edited})
    evidence = scenario["direct_0"]["evidence"]
    assert evidence[0]["kind"] == "expert_assumption"
    assert evidence[0]["author"] == "analyst"
    assert evidence[0]["as_of"] == str(date.today())
    assert evidence[0]["locator"] == "p1/para2/s1"
    assert evidence[0]["fragment_sha256"] == OTHER_SHA
    assert evidence[0]["source_id"] == "event-doc"


def test_unchanged_magnitude_with_a_changed_label_keeps_the_evidence():
    original = llm_evidence()
    proposed = triangular(mode=-0.1, label="старая метка", evidence=[original]).model_dump(
        mode="json"
    )
    edited = triangular(mode=-0.1, label="новая метка", evidence=[original])
    scenario = edited_by("analyst", {"channel_shock": proposed}, {"channel_shock": edited})
    assert scenario["channel_shock"]["evidence"] == proposed["evidence"]
    assert scenario["channel_shock"]["label"] == "новая метка"


def test_a_parameter_changed_to_another_kind_counts_as_changed():
    proposed = point(value=-0.1, evidence=[llm_evidence()]).model_dump(mode="json")
    edited = triangular(mode=-0.1, label="direct_0", evidence=[llm_evidence()])
    scenario = edited_by("analyst", {"direct_0": proposed}, {"direct_0": edited})
    evidence = scenario["direct_0"]["evidence"]
    assert evidence[0]["kind"] == "expert_assumption"
    assert evidence[0]["author"] == "analyst"


def test_a_changed_parameter_with_empty_evidence_gets_the_analyst_evidence():
    proposed = triangular(mode=-0.1, evidence=[]).model_dump(mode="json")
    edited = triangular(mode=-0.05, evidence=[])
    scenario = edited_by("analyst", {"channel_shock": proposed}, {"channel_shock": edited})
    spec = scenario["channel_shock"]
    evidence = spec["evidence"]
    assert len(evidence) == 1
    assert evidence[0]["kind"] == "expert_assumption"
    assert evidence[0]["source_id"] == ANALYST_SCENARIO
    assert evidence[0]["locator"] == "/macro_parameters/channel_shock"
    assert evidence[0]["author"] == "analyst"
    assert evidence[0]["as_of"] == str(date.today())
    ScenarioParameter.model_validate(spec)


def test_an_unchanged_parameter_with_empty_evidence_stays_empty():
    proposed = triangular(mode=-0.1, evidence=[]).model_dump(mode="json")
    edited = triangular(mode=-0.1, evidence=[])
    scenario = edited_by("analyst", {"channel_shock": proposed}, {"channel_shock": edited})
    assert scenario["channel_shock"]["evidence"] == []


def test_a_parameter_absent_from_proposed_gets_the_analyst_evidence():
    edited = triangular(mode=-0.05, evidence=[])
    scenario = edited_by("analyst", {}, {"channel_shock": edited})
    evidence = scenario["channel_shock"]["evidence"]
    assert len(evidence) == 1
    assert evidence[0]["kind"] == "expert_assumption"
    assert evidence[0]["source_id"] == ANALYST_SCENARIO
    assert evidence[0]["locator"] == "/macro_parameters/channel_shock"
    assert evidence[0]["author"] == "analyst"
    assert evidence[0]["as_of"] == str(date.today())
    ScenarioParameter.model_validate(scenario["channel_shock"])


def test_the_registry_words_the_analyst_scenario_source():
    assert registry().source_wording()[ANALYST_SCENARIO] == "сценарий, заданный аналитиком"


def test_every_returned_spec_revalidates_as_a_scenario_parameter():
    proposed = {
        "channel_shock": triangular(mode=-0.1, evidence=[llm_evidence()]).model_dump(mode="json"),
        "direct_0": point(value=-0.1, evidence=[document_evidence()]).model_dump(mode="json"),
    }
    edited = {
        "channel_shock": triangular(mode=-0.05, evidence=[llm_evidence()]),
        "direct_0": point(value=-0.1, evidence=[document_evidence()]),
    }
    scenario = edited_by("analyst", proposed, edited)
    for spec in scenario.values():
        ScenarioParameter.model_validate(spec)


def nudge(low, mode, high):
    """A mode inside ``(low, high)``, guaranteed different from the current one."""
    candidate = low + (high - low) * 0.9
    return candidate if candidate != mode else low + (high - low) * 0.1


def test_a_resumed_edit_is_attributed_to_the_analyst_at_the_api(client):  # noqa: F811
    """An estimated parameter the analyst edits on resume is attributed to them; an
    untouched one keeps the model's attribution."""
    saved = post(
        client,
        "/v1/demo/portfolios/draft",
        {
            "name": "Проверка правок аналитика",
            "positions": [
                {
                    "position_id": "EQ1",
                    "name": "Эмитент",
                    "instrument_type": "common_stock",
                    "okved": "46.63",
                    "values": {
                        "quantity": 100,
                        "ticker": "TEST",
                        "price": 250,
                        "beta_market": 1,
                        "beta_sector": 1,
                        "residual_volatility": 0,
                        "dividend": 0,
                    },
                }
            ],
        },
    )
    status = post(
        client,
        "/v1/demo/runs",
        {
            "portfolio_id": saved["portfolio_id"],
            # Not a library event: the mock profile's generic answer estimates every direct
            # factor's magnitude for the analyst to confirm or change.
            "event": {"kind": "text", "text": "Введён утилизационный сбор на спецтехнику."},
        },
    )
    status = wait(client, status["run_id"])
    assert status["status"] == "human_fix_graph"
    stop = status["pending_interrupt"][0]["payload"]
    parameters = stop["macro_parameters"]
    assert {"channel_shock", "direct_0"} <= set(parameters)

    edited_parameter = dict(parameters["channel_shock"])
    edited_parameter["mode"] = nudge(
        edited_parameter["low"], edited_parameter["mode"], edited_parameter["high"]
    )
    edited_parameters = {**parameters, "channel_shock": edited_parameter}

    post(
        client,
        f"/v1/demo/runs/{status['run_id']}/resume",
        {"graph": stop["graph"], "macro_parameters": edited_parameters},
    )
    wait(client, status["run_id"])

    confirmed = get(client, f"/v1/demo/runs/{status['run_id']}/artifacts")["scenario"]["parameters"]
    edited_evidence = confirmed["channel_shock"]["evidence"]
    assert edited_evidence
    assert all(e["author"] == "analyst" for e in edited_evidence)
    assert all(e["kind"] == "expert_assumption" for e in edited_evidence)

    unedited_evidence = confirmed["direct_0"]["evidence"]
    assert unedited_evidence
    assert all(e["author"].startswith("LLM:") for e in unedited_evidence)


def test_a_parameter_added_on_resume_is_attributed_to_the_analyst_at_the_api(client):  # noqa: F811
    """A parameter the analyst adds from scratch on resume cites the analyst's scenario."""
    saved = post(
        client,
        "/v1/demo/portfolios/draft",
        {
            "name": "Проверка добавленного параметра",
            "positions": [
                {
                    "position_id": "EQ1",
                    "name": "Эмитент",
                    "instrument_type": "common_stock",
                    "okved": "46.63",
                    "values": {
                        "quantity": 100,
                        "ticker": "TEST",
                        "price": 250,
                        "beta_market": 1,
                        "beta_sector": 1,
                        "residual_volatility": 0,
                        "dividend": 0,
                    },
                }
            ],
        },
    )
    status = post(
        client,
        "/v1/demo/runs",
        {
            "portfolio_id": saved["portfolio_id"],
            # Not a library event: the mock profile's generic answer estimates every direct
            # factor's magnitude for the analyst to confirm or change.
            "event": {"kind": "text", "text": "Введён утилизационный сбор на спецтехнику."},
        },
    )
    status = wait(client, status["run_id"])
    assert status["status"] == "human_fix_graph"
    stop = status["pending_interrupt"][0]["payload"]
    parameters = stop["macro_parameters"]
    assert "channel_shock" in parameters

    added_parameter = {
        **parameters["channel_shock"],
        "label": "добавлено аналитиком",
        "evidence": [],
    }
    edited_parameters = {**parameters, "analyst_added": added_parameter}

    post(
        client,
        f"/v1/demo/runs/{status['run_id']}/resume",
        {"graph": stop["graph"], "macro_parameters": edited_parameters},
    )
    wait(client, status["run_id"])

    confirmed = get(client, f"/v1/demo/runs/{status['run_id']}/artifacts")["scenario"]["parameters"]
    added_evidence = confirmed["analyst_added"]["evidence"]
    assert len(added_evidence) == 1
    assert added_evidence[0]["author"] == "analyst"
    assert added_evidence[0]["kind"] == "expert_assumption"
    assert added_evidence[0]["source_id"] == ANALYST_SCENARIO
