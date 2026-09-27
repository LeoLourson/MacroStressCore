"""CausalAgent._verify_model_context: the message names the factor, its keys and the parameter."""

from dataclasses import asdict

import pytest

from msa.agents.base import AgentError
from msa.agents.causal import CausalAgent
from msa.agents.causal_output import CausalOutput
from msa.platform.registry import registry

EVENT = {"id": "event", "kind": "event", "label": "event"}


def factor(factor_id):
    return asdict(registry().factors[factor_id])


def context(*references):
    return {
        "factors": [factor("equity.market"), factor("equity.sector")],
        "positions": [
            {"factors": [{"factor_id": name, "key": key} for name, key in references]}
        ],
    }


def factor_node(factor_id, key):
    return {
        "id": f"{factor_id}:{key}",
        "kind": "factor",
        "label": "f",
        "factor": factor_id,
        "key": key,
    }


def output(*, nodes=(EVENT,), scenario=None):
    return CausalOutput.model_validate(
        {
            "passport": {"event_type": "event"},
            "parameters": {},
            "direct_okved": [],
            "inferred_okved": [],
            "graph": {"event_id": "event", "nodes": list(nodes), "edges": []},
            "scenario": scenario or {},
        }
    )


def parameter(**overrides):
    base = {"label": "шок", "kind": "point", "value": 0.1, "unit": "fraction"}
    base.update(overrides)
    return base


def test_an_unused_key_names_the_node_and_lists_the_portfolio_keys():
    ctx = context(("equity.market", "MOEX"), ("equity.market", "RTS"))
    with pytest.raises(AgentError) as exc:
        CausalAgent._verify_model_context(
            output(nodes=(EVENT, factor_node("equity.market", "SP500"))), ctx
        )
    message = str(exc.value)
    assert "Factor node equity.market:SP500" in message
    assert "equity.market with key SP500 is not used" in message
    assert "its keys here: MOEX, RTS" in message


def test_a_factor_no_position_reads_says_so():
    ctx = context(("equity.sector", "trade"), ("equity.sector", "telecom"))
    with pytest.raises(AgentError) as exc:
        CausalAgent._verify_model_context(
            output(nodes=(EVENT, factor_node("equity.market", "MOEX"))), ctx
        )
    message = str(exc.value)
    assert "Factor node equity.market:MOEX" in message
    assert "no position reads it" in message


def test_a_scenario_parameter_without_a_factor_moves_no_factor():
    ctx = context(("equity.market", "MOEX"))
    with pytest.raises(AgentError) as exc:
        CausalAgent._verify_model_context(output(scenario={"shock": parameter()}), ctx)
    assert "Scenario parameter shock moves no factor" in str(exc.value)


def test_a_scenario_parameter_with_an_unused_key_names_the_parameter_and_keys():
    ctx = context(("equity.market", "MOEX"), ("equity.sector", "trade"))
    unused = parameter(factor="equity.market", key="SP500", unit="log_return")
    with pytest.raises(AgentError) as exc:
        CausalAgent._verify_model_context(output(scenario={"shock": unused}), ctx)
    message = str(exc.value)
    assert "Scenario parameter shock" in message
    assert "equity.market with key SP500 is not used" in message
    assert "its keys here: MOEX" in message
