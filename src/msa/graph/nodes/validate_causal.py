from msa.agents.causal_output import scenario_violations
from msa.db.repositories.runs import json_payload
from msa.engine.exposure import scenario_coverage
from msa.plugin_sdk.model import RunOptions


def coverage(state, graph, parameters, context):
    return scenario_coverage(
        state.get("portfolio_positions") or [],
        graph,
        parameters,
        RunOptions(
            as_of=state["as_of"],
            horizon=state.get("horizon", 12),
            base_currency=state.get("base_currency", "RUB"),
            options=context.options,
        ),
        context.registry,
    )


def run(state, *, context):
    graph, parameters = state["graph"], state.get("macro_parameters") or {}
    verdicts = json_payload(context.validate("TransmissionGraph", graph))
    # Scenario errors must reach the causal retry, before the analyst's approval stop.
    verdicts += scenario_violations(
        parameters, graph, required=state.get("scenario_required", False)
    )
    verdicts += coverage(state, graph, parameters, context)
    return {"verdicts": verdicts}
