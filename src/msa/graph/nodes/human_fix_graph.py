from langgraph.types import interrupt

from msa.agents.causal_output import scenario_violations
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
    # No writes or calls to agents before interrupt; invalid edits ask again.
    parameters = state.get("macro_parameters") or {}
    required = state.get("scenario_required", False)
    errors = (
        state.get("verdicts", [])
        + scenario_violations(parameters, state["graph"], required=required)
        + coverage(state, state["graph"], parameters, context)
    )
    while True:
        answer = interrupt(
            {
                "kind": "human_fix_graph",
                "run_id": state["run_id"],
                "graph": state["graph"],
                "attempts": state["attempts"],
                "violations": errors,
                "macro_parameters": parameters,
                "scenario_required": required,
                # Set when the risk manager sent the report back: the task for this stop.
                "decision": state.get("decision"),
            }
        )
        answer = answer if isinstance(answer, dict) else {}
        candidate = answer.get("graph")
        # Resuming without parameters confirms the proposed scenario unchanged.
        parameters = answer.get("macro_parameters", parameters)
        verdicts = context.validate("TransmissionGraph", candidate)
        problems = scenario_violations(parameters, candidate, required=required)
        problems += coverage(state, candidate, parameters, context)
        if verdicts and all(v.ok for v in verdicts) and not problems:
            return {
                "graph": candidate,
                "graph_revision": state["graph_revision"] + 1,
                "request_graph_review": False,
                "macro_parameters": parameters,
                "scenario_confirmed": True,
                # A new round starts here; results of the previous one must not add up.
                "position_results": None,
                "position_draws": None,
                "errors": [],
            }
        errors = [v.model_dump(mode="json") for v in verdicts] + problems
