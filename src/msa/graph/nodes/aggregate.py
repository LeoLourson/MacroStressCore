from datetime import date

from msa.agents.aggregate import AggregateInput
from msa.agents.base import AgentFailure
from msa.agents.draw_macro import ScenarioDraws
from msa.contracts import CalculationResult, PortfolioResult
from msa.plugin_sdk.model import Diagnostics
from msa.validators.v11_macro_hash import check


def run(state, *, context):
    results = sorted(
        (CalculationResult.model_validate(r) for r in state.get("position_results") or []),
        key=lambda result: result.position_id,
    )
    ids = [result.position_id for result in results]
    expected = sorted(p["position"]["position_id"] for p in state.get("positions") or [])
    if len(set(ids)) != len(ids) or ids != expected:
        raise AgentFailure(["Missing, duplicate or unexpected position branches"])
    draws = ScenarioDraws.model_validate(state["scenario_set"])
    if draws.sha256 != state["macro_draws_sha256"] or draws.scenario_id != state["scenario_id"]:
        raise AgentFailure(["Shared scenario set was changed after fan-out"])
    verdicts = check(results, expected_hash=draws.sha256)
    if any(not v.ok for v in verdicts):
        return {
            "v11_verdicts": verdicts,
            "status": "needs_review",
            "errors": [v.message for v in verdicts if not v.ok],
        }
    update = {"sorted_results": results, "v11_verdicts": verdicts}
    if not results:
        # The scenario reaches no position of the portfolio: nothing to aggregate.
        return update | {"portfolio_result": None}
    exposures = {
        position_id: dict(Diagnostics.model_validate(raw).exposures)
        for position_id, raw in (state.get("diagnostics") or {}).items()
    }
    portfolio = context.call(
        "aggregate",
        AggregateInput(
            run_id=state["run_id"],
            results=results,
            draws={
                item["position_id"]: item["draws"] for item in state.get("position_draws") or []
            },
            exposures=exposures,
            base_currency=state.get("base_currency", "RUB"),
            as_of=date.fromisoformat(state["as_of"]),
            horizon=state.get("horizon", 12),
            seed=state["seed"],
            scenario_id=draws.scenario_id,
            macro_draws_sha256=draws.sha256,
        ),
        PortfolioResult,
    )
    if portfolio.run_id != state["run_id"] or portfolio.macro_draws_sha256 != draws.sha256:
        raise AgentFailure(["Portfolio run_id or scenario hash differs from run"])
    return update | {"portfolio_result": portfolio}
