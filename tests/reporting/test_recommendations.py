"""msa.reporting.recommendations: thresholds_in_force() and apply()."""

from datetime import date

import pytest

from msa.contracts.result import CalculationResult, MetricValue
from msa.platform.registry import build
from msa.plugin_sdk.plugin import Plugin
from msa.plugin_sdk.specs import ActionSpec, RecommendationRule
from msa.reporting.recommendations import OPERATORS, apply, thresholds_in_force

SHA = "a" * 64


def observe_metric(name):
    def _observe(result, context):
        value = result.metrics.get(name)
        if value is None:
            return None
        return value.value, f"/positions/{result.position_id}/metrics/{name}"

    return _observe


def registry(*, r2_fallback=True):
    rule1 = RecommendationRule(
        rule_id="test.R1",
        label="R1",
        observation="test.m1",
        operator="ge",
        threshold=1.0,
        actions=("act1",),
    )
    rule2 = RecommendationRule(
        rule_id="test.R2",
        label="R2",
        observation="test.m2",
        operator="lt",
        threshold=0.5,
        actions=("act2",),
        fallback_only=r2_fallback,
    )
    plugin = Plugin(
        plugin_id="test",
        version="1.0.0",
        sdk=">=1.0,<2.0",
        label="T",
        rules=(rule1, rule2),
        actions=(ActionSpec("act1", "Action 1"), ActionSpec("act2", "Action 2")),
        observations={"test.m1": observe_metric("m1"), "test.m2": observe_metric("m2")},
    )
    return build([plugin])


def result(*, m1=None, m2=None, status="ok", execution="completed"):
    metrics = {}
    if m1 is not None:
        metrics["m1"] = MetricValue(metric_id="m1", unit="fraction", value=m1)
    if m2 is not None:
        metrics["m2"] = MetricValue(metric_id="m2", unit="fraction", value=m2)
    values = dict(
        position_id="POS1",
        instrument_id="I1",
        instrument_type="t",
        plugin_id="test",
        plugin_version="1.0.0",
        model_id="test.m",
        model_version="1.0.0",
        as_of=date(2026, 1, 1),
        horizon=12,
        seed=1,
        execution=execution,
        status=status,
        scenario_id=SHA,
        metrics=metrics,
    )
    if execution != "completed" or status in ("needs_review", "incomplete", "invalid"):
        values["flags"] = ["reason"]
    return CalculationResult(**values)


# -- OPERATORS --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("operator", "value", "threshold", "expected"),
    [
        ("lt", 1.0, 2.0, True),
        ("lt", 2.0, 2.0, False),
        ("le", 2.0, 2.0, True),
        ("le", 2.1, 2.0, False),
        ("gt", 2.0, 1.0, True),
        ("gt", 1.0, 1.0, False),
        ("ge", 1.0, 1.0, True),
        ("ge", 0.9, 1.0, False),
    ],
)
def test_operators(operator, value, threshold, expected):
    assert OPERATORS[operator](value, threshold) is expected


# -- thresholds_in_force() ---------------------------------------------------------------


def test_thresholds_in_force_uses_declared_defaults_when_nothing_stored():
    reg = registry()
    rules, defaults = thresholds_in_force(reg, None)
    assert set(defaults) == {"test.R1", "test.R2"}
    assert rules["test.R1"]["threshold"] == 1.0
    assert rules["test.R1"]["operator"] == "ge"
    assert rules["test.R1"]["actions"] == ["act1"]


def test_thresholds_in_force_uses_stored_row_when_present():
    reg = registry()
    stored = {
        "test.R1": {"metric": "test.m1", "operator": "ge", "threshold": 5.0, "actions": ["act1"]},
    }
    rules, defaults = thresholds_in_force(reg, stored)
    assert rules["test.R1"]["threshold"] == 5.0
    assert defaults == ["test.R2"]


# -- apply(): firing, order, fallback_only -----------------------------------------------


def test_apply_fires_a_rule_whose_condition_holds():
    reg = registry()
    thresholds, _ = thresholds_in_force(reg, None)
    r = result(m1=2.0)
    recs = apply(r, reg, thresholds)
    assert len(recs) == 1
    assert recs[0].action == "act1"
    assert recs[0].rule_id == "test.R1"
    assert recs[0].metric_refs == ["/positions/POS1/metrics/m1"]


def test_apply_skips_a_rule_whose_condition_does_not_hold():
    reg = registry()
    thresholds, _ = thresholds_in_force(reg, None)
    r = result(m1=0.5)
    assert apply(r, reg, thresholds) == []


def test_apply_skips_a_rule_whose_observation_returns_none():
    reg = registry()
    thresholds, _ = thresholds_in_force(reg, None)
    r = result()  # neither m1 nor m2 present
    assert apply(r, reg, thresholds) == []


def test_apply_fallback_rule_does_not_fire_after_another_rule_fired():
    reg = registry(r2_fallback=True)
    thresholds, _ = thresholds_in_force(reg, None)
    r = result(m1=2.0, m2=0.1)  # both R1 and R2's raw conditions hold
    recs = apply(r, reg, thresholds)
    assert [rec.rule_id for rec in recs] == ["test.R1"]


def test_apply_fallback_rule_fires_when_nothing_else_fired():
    reg = registry(r2_fallback=True)
    thresholds, _ = thresholds_in_force(reg, None)
    r = result(m2=0.1)  # only R2's condition can hold; R1's observation is absent
    recs = apply(r, reg, thresholds)
    assert [rec.rule_id for rec in recs] == ["test.R2"]


def test_apply_non_fallback_rules_both_fire_in_declared_order():
    reg = registry(r2_fallback=False)
    thresholds, _ = thresholds_in_force(reg, None)
    r = result(m1=2.0, m2=0.1)
    recs = apply(r, reg, thresholds)
    assert [rec.rule_id for rec in recs] == ["test.R1", "test.R2"]


def test_apply_uses_stored_thresholds_not_declared_defaults():
    reg = registry()
    stored = {
        "test.R1": {"metric": "test.m1", "operator": "ge", "threshold": 10.0, "actions": ["act1"]},
    }
    thresholds, _ = thresholds_in_force(reg, stored)
    # Below the stored threshold of 10, though above the declared default of 1.
    r = result(m1=2.0)
    assert apply(r, reg, thresholds) == []


# -- not-completed / invalid results give nothing -----------------------------------------


def test_apply_gives_nothing_for_a_result_that_did_not_complete():
    reg = registry()
    thresholds, _ = thresholds_in_force(reg, None)
    r = result(execution="not_run", status="needs_review")
    assert apply(r, reg, thresholds) == []


def test_apply_gives_nothing_for_an_invalid_result():
    reg = registry()
    thresholds, _ = thresholds_in_force(reg, None)
    r = result(m1=2.0, status="invalid")
    assert apply(r, reg, thresholds) == []


def test_apply_unknown_plugin_gives_nothing():
    reg = registry()
    thresholds, _ = thresholds_in_force(reg, None)
    r = result(m1=2.0)
    r = r.model_copy(update={"plugin_id": "no_such_plugin"})
    assert apply(r, reg, thresholds) == []
