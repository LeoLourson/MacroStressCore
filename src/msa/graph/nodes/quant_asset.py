from datetime import date

from msa.agents.base import AgentFailure
from msa.agents.draw_macro import ScenarioDraws
from msa.agents.quant import QuantInput, not_calculated
from msa.engine.model_catalog import ModelRunOutput
from msa.plugin_sdk.model import Diagnostics


def run(state, *, context):
    position_id = state["branch_position_id"]
    position = next(p for p in state["positions"] if p["position"]["position_id"] == position_id)
    prepared = (state.get("prepared") or {}).get(position_id)
    payload = QuantInput(
        context=position,
        prepared=prepared,
        diagnostics=Diagnostics.model_validate((state.get("diagnostics") or {})[position_id]),
        draws=ScenarioDraws.model_validate(state["scenario_set"]),
        graph=state.get("graph") or None,
        as_of=date.fromisoformat(state["as_of"]),
        horizon=state.get("horizon", 12),
        snapshot_id=state["snapshot_id"],
        base_currency=state.get("base_currency", "RUB"),
        options=context.options,
        run_id=state["run_id"],
    )
    # Each branch owns a separately validated copy; accidental mutation cannot reach its peers.
    try:
        output = context.call("quant", payload.model_copy(deep=True), ModelRunOutput)
        result = output.result
        if result.position_id != position_id or result.seed != payload.draws.seed:
            raise AgentFailure(["Quant returned another position or seed"])
        if result.as_of != payload.as_of or result.horizon != payload.horizon:
            raise AgentFailure(["Quant returned another valuation date or horizon"])
    except AgentFailure as exc:
        output = not_calculated(payload, context.registry, "quant_failure:" + str(exc)[:80])
    except Exception as exc:
        # One degenerate branch must not abort the fan-out; it stays in the run as invalid.
        output = not_calculated(payload, context.registry, f"quant_failure:{type(exc).__name__}")
    update = {"position_results": [output.result]}
    if output.draws:
        update["position_draws"] = [{"position_id": position_id, "draws": output.draws}]
    return update
