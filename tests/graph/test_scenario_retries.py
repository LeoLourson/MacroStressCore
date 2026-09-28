"""An incomplete causal scenario uses the same repair budget as an invalid graph."""

import pytest

from msa.graph.interrupts import start_run
from tests.support import SCENARIO, ScriptedCausal, agents, confirm, run_input, stop


class RepairingCausal(ScriptedCausal):
    def __init__(self, *, repairs=True, invalid_channel=False):
        super().__init__()
        self.repairs = repairs
        self.invalid_channel = invalid_channel

    def run_structured(self, payload):
        output = super().run_structured(payload)
        if not self.repairs or len(self.calls) == 1:
            if self.invalid_channel:
                output.scenario["demand_drop"].channel = "absent_channel"
            else:
                # A valid parameter for another factor does not cover the graph's revenue.
                output.scenario["demand_drop"].factor = "credit.cogs"
        return output


@pytest.mark.parametrize("invalid_channel", [False, True])
def test_scenario_problems_reach_the_causal_retry_before_human_review(
    graph_factory, invalid_channel
):
    causal = RepairingCausal(invalid_channel=invalid_channel)
    configured = agents(causal=causal)
    graph, _ = graph_factory(agents=configured)
    state = start_run(graph, run_input("scenario-repair"))
    assert state["attempts"] == len(causal.calls) == 2
    assert any(v["rule_id"] == "SCENARIO" for v in causal.calls[1]["violations"])
    pending = stop(graph, "scenario-repair")
    assert all(v["ok"] for v in pending["violations"])
    assert pending["macro_parameters"]["demand_drop"]["factor"] == "credit.revenue"
    assert configured.quant.calls == []
    confirm(graph, "scenario-repair")
    assert len(causal.calls) == 2  # A confirmed correction does not start another LLM loop.


@pytest.mark.parametrize("auto_approve", [False, True])
def test_exhausted_scenario_repairs_keep_the_draft_and_block_calculation(
    graph_factory, auto_approve
):
    causal = RepairingCausal(repairs=False)
    configured = agents(causal=causal)
    graph, _ = graph_factory(agents=configured, auto_approve_demo=auto_approve)
    state = start_run(graph, run_input("scenario-exhausted"))
    assert state["attempts"] == len(causal.calls) == 3
    pending = stop(graph, "scenario-exhausted")
    problems = [v for v in pending["violations"] if not v["ok"]]
    assert problems and len(problems) == len({str(v) for v in problems})
    assert pending["graph"]["nodes"]
    assert pending["macro_parameters"]["demand_drop"]["factor"] == "credit.cogs"
    assert configured.quant.calls == []
    confirm(graph, "scenario-exhausted", macro_parameters=SCENARIO)
    assert configured.quant.calls  # The analyst's scenario reaches the calculation.
    assert len(causal.calls) == 3
