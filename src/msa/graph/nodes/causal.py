from datetime import date

from msa.agents.base import AgentError
from msa.db.repositories.runs import json_payload
from msa.engine.causal_context import portfolio_context
from msa.plugin_sdk.model import RunOptions


def model_context(state, context):
    options = RunOptions(
        as_of=date.fromisoformat(state["as_of"]),
        horizon=state.get("horizon", 12),
        base_currency=state.get("base_currency", "RUB"),
        options=context.options,
    )
    return portfolio_context(state.get("portfolio_positions") or [], options, context.registry)


def run(state, *, context):
    # One call per graph iteration: graph routing owns the total budget of three.
    # The calculation draws only from a confirmed scenario: the analyst must see one.
    update = {"scenario_required": True}
    payload = {
        "document": state["document"],
        "attempt": state["attempts"] + 1,
        "graph": state.get("graph"),
        # The agent's own rejection reason precedes V1 errors of the empty graph.
        "violations": state.get("errors", [])
        + [v for v in state.get("verdicts", []) if not v["ok"]],
        "okved_scope": sorted(
            {
                (p.get("issuer") or {}).get("okved")
                for p in state.get("portfolio_positions") or []
                if (p.get("issuer") or {}).get("okved")
            }
        ),
        "seed": state["seed"],
    }
    try:
        payload["portfolio_context"] = model_context(state, context)
        output = context.agents.causal.run_structured(payload)
        graph = json_payload(output.graph)
        update.update(
            event_passport=json_payload(output.passport),
            event_parameters=json_payload(output.parameters),
            macro_parameters=json_payload(output.scenario),
            # Demo auto-approval also stands in for the analyst's confirmation.
            scenario_confirmed=context.auto_approve_demo,
        )
        errors = []
    # ValueError covers unparseable LLM answers (JSON decode, schema validation).
    except (AgentError, ValueError) as exc:
        graph, errors = {}, [str(exc)]
    except OSError as exc:
        # Endpoint timeouts and HTTP errors share the same budget of three attempts.
        graph, errors = {}, [f"LLM request failed: {exc}"]
    return {**update, "graph": graph, "attempts": state["attempts"] + 1, "errors": errors}
