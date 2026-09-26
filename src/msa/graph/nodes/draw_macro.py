from msa.agents.base import AgentFailure
from msa.agents.causal_output import ScenarioParameter
from msa.agents.draw_macro import DrawInput, ScenarioDraws
from msa.plugin_sdk.model import Diagnostics


def run(state, *, context):
    shocks = [
        shock
        for raw in (state.get("diagnostics") or {}).values()
        for shock in Diagnostics.model_validate(raw).idiosyncratic
    ]
    draws = context.call(
        "draw_macro",
        DrawInput(
            graph=state.get("graph") or None,
            seed=state["seed"],
            mc_points=state["mc_points"],
            as_of=state["as_of"],
            horizon=state.get("horizon", 12),
            parameters={
                name: ScenarioParameter.model_validate({"label": name, **spec}).macro()
                for name, spec in (state.get("macro_parameters") or {}).items()
            },
            idiosyncratic=shocks,
        ),
        ScenarioDraws,
    )
    if draws.seed != state["seed"] or draws.points * draws.replicates != state["mc_points"]:
        raise AgentFailure(["Scenario matrix seed or size differs from run input"])
    return {
        "scenario_set": draws,
        "scenario_id": draws.scenario_id,
        "macro_draws_sha256": draws.sha256,
    }
