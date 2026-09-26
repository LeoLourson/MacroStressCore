"""msa.agents.causal_output.scenario_violations: the factor's declared lower bound."""

from msa.agents.causal_output import scenario_violations
from msa.plugin_sdk.testing import graph_reaching

GRAPH = graph_reaching("23.61", "credit.revenue")


def parameter(**overrides):
    base = {
        "label": "Шок выручки",
        "kind": "point",
        "value": -0.2,
        "unit": "fraction",
        "factor": "credit.revenue",
        "channel": "channel",
    }
    base.update(overrides)
    return base


def has_bound_problem(problems):
    return any(
        p["rule_id"] == "SCENARIO" and "должно быть больше" in p["message"] for p in problems
    )


def test_point_value_at_the_factor_lower_bound_is_rejected():
    problems = scenario_violations({"p1": parameter(kind="point", value=-1.0)}, GRAPH)
    assert has_bound_problem(problems)


def test_triangular_low_at_the_factor_lower_bound_is_rejected():
    scenario = {"p1": parameter(kind="triangular", value=None, low=-1.2, mode=-0.5, high=-0.1)}
    problems = scenario_violations(scenario, GRAPH)
    assert has_bound_problem(problems)


def test_point_value_within_the_bound_raises_no_bound_problem():
    problems = scenario_violations({"p1": parameter(kind="point", value=-0.99)}, GRAPH)
    assert problems == []
