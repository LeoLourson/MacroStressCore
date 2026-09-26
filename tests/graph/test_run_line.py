"""The run from the event text to the published report, through both human stops."""

from msa.agents.causal_output import ScenarioParameter
from msa.graph.interrupts import pending_interrupt, resume_run, start_run

from ..support import SCENARIO, agents, confirm, run_input, stop


def test_the_scenario_waits_for_the_analyst_before_any_calculation(graph_factory):
    quant = agents().quant
    graph, _ = graph_factory(agents=agents(quant=quant))
    state = start_run(graph, run_input("wait"))
    payload = stop(graph, "wait")
    assert payload["kind"] == "human_fix_graph"
    assert {
        name: ScenarioParameter.model_validate(spec)
        for name, spec in payload["macro_parameters"].items()
    } == {name: ScenarioParameter.model_validate(spec) for name, spec in SCENARIO.items()}
    assert payload["scenario_required"] is True
    assert state["event_passport"]["event_type"] == "Утилизационный сбор"
    assert quant.calls == []


def test_calculated_run_reaches_approval_and_publishes(graph_factory):
    graph, journal = graph_factory(agents=agents(calculate=True))
    start_run(graph, run_input("line"))
    state = confirm(graph, "line")
    assert stop(graph, "line")["kind"] == "human_approval"
    results = state["sorted_results"]
    assert [r["position_id"] for r in results] == ["A3", "A5"]
    assert {r["macro_draws_sha256"] for r in results} == {state["macro_draws_sha256"]}
    assert {r["scenario_id"] for r in results} == {state["scenario_id"]}
    assert all(r["model_id"] == "credit.corporate.v3" for r in results)
    loss = results[0]["metrics"]["credit.delta_expected_loss"]["quantiles"]
    assert loss["p05"] <= loss["p50"] <= loss["p95"] and loss["p50"] > 0
    credit = state["portfolio_result"]["slices"]["credit.loss"]
    assert set(credit["included"]) == {"A3", "A5"}
    assert "market.pnl" not in state["portfolio_result"]["slices"]

    state = resume_run(graph, "line", {"approved": True, "approved_by": "risk"})
    assert state["status"] == "published" and state["published"] is True
    assert state["report"]["approved_by"] == "risk"
    assert pending_interrupt(graph, "line") == []
    nodes = {row["node"] for row in journal.list_node_results("line")}
    assert {"quant_agent/A3", "quant_agent/A5", "aggregate", "publish"} <= nodes


def test_positions_outside_the_event_sectors_are_not_calculated(graph_factory):
    quant = agents().quant
    causal = agents().causal
    # The graph reaches only A3's sector.
    causal.run_structured = _only_sector(causal.run_structured, "46.63")
    graph, _ = graph_factory(agents=agents(quant=quant, causal=causal))
    start_run(graph, run_input("select"))
    confirm(graph, "select")
    assert quant.calls == ["A3"]


def _only_sector(run_structured, okved):
    def run(payload):
        return run_structured({**payload, "okved_scope": [okved]})

    return run


def test_share_with_only_operating_shock_waits_for_market_scenario(graph_factory):
    from tests.support import positions

    share = next(p for p in positions() if p["instrument"]["instrument_type"] == "common_stock")
    graph, _ = graph_factory(agents=agents(calculate=True))
    start_run(graph, run_input("share-scenario", portfolio_positions=[share]))
    payload = stop(graph, "share-scenario")
    assert payload["kind"] == "human_fix_graph"
    assert any("Потери пока не оценены" in v["message"] for v in payload["violations"])
    # Confirming the incomplete scenario must not create an empty report.
    confirm(graph, "share-scenario")
    payload = stop(graph, "share-scenario")
    assert payload["kind"] == "human_fix_graph"
    parameters = {
        **payload["macro_parameters"],
        "sector_change": {
            "label": "Изменение отрасли",
            "kind": "point",
            "value": -0.1,
            "unit": "log_return",
            "factor": "equity.sector",
            "key": share["instrument"]["terms"]["sector"],
        },
    }
    state = resume_run(
        graph,
        "share-scenario",
        {
            "graph": payload["graph"],
            "macro_parameters": parameters,
        },
    )
    assert stop(graph, "share-scenario")["kind"] == "human_approval"
    assert state["sorted_results"][0]["execution"] == "completed"
    assert "equity.pnl" in state["sorted_results"][0]["metrics"]
