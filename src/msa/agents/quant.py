"""Quant Agent (TZ 3.5): one position through its model.

The agent runs the position's registered model through ``mcp-models.run_model`` (TZ 5), so
the calculation is an audited tool call of the run. Without a tool gateway (tests, direct
use) it calls the same catalog directly. A position whose inputs did not pass its model's
check stays in the run with the reason and without numbers.
"""

from datetime import date

from pydantic import BaseModel, Field

from msa.contracts.domain import PositionContext
from msa.engine.catalog import ModelRunOutput, run_model
from msa.engine.dispatch import not_run
from msa.plugin_sdk.model import Diagnostics, PreparedInputs

from .draw_macro import ScenarioDraws


class QuantInput(BaseModel):
    context: PositionContext
    prepared: PreparedInputs | None
    diagnostics: Diagnostics
    draws: ScenarioDraws
    graph: dict | None = None
    as_of: date
    horizon: int = Field(default=12, ge=1, le=360)
    snapshot_id: str
    base_currency: str = "RUB"
    options: dict = {}
    run_id: str | None = None


def not_calculated(payload: QuantInput, registry, reason=None, *, status=None) -> ModelRunOutput:
    """The position without numbers: its model's verdict, or ``reason`` when there is none."""
    diagnostics = payload.diagnostics
    if reason is not None:
        diagnostics = Diagnostics(
            items=[*diagnostics.items, {"code": reason, "severity": "error", "message": reason}],
            exposures=diagnostics.exposures,
            data_quality=diagnostics.data_quality,
            blocked_status=status or "invalid",
        )
    result = not_run(
        payload.context,
        diagnostics,
        registry,
        as_of=payload.as_of,
        horizon=payload.horizon,
        seed=payload.draws.seed,
        scenario_id=payload.draws.scenario_id,
        snapshot_id=payload.snapshot_id,
        macro_draws_sha256=payload.draws.sha256,
        model_id=payload.prepared.model_id if payload.prepared else None,
    )
    return ModelRunOutput(result=result, draws={}, code_sha256=result.code_sha256)


class QuantAgent:
    def __init__(self, *, registry, tools=None):
        self.registry, self.tools = registry, tools

    def run(self, payload: QuantInput) -> ModelRunOutput:
        if payload.prepared is None or payload.diagnostics.blocking:
            return not_calculated(payload, self.registry)
        arguments = {
            "model_id": payload.prepared.model_id,
            "payload": {
                "prepared": payload.prepared.model_dump(mode="json"),
                "diagnostics": payload.diagnostics.model_dump(mode="json"),
                "scenario": {
                    "spec": payload.draws.spec,
                    "seed": payload.draws.seed,
                    "as_of": payload.as_of.isoformat(),
                    "horizon": payload.horizon,
                    "graph": payload.graph,
                    "factor_versions": payload.draws.factor_versions,
                    "macro_draws_sha256": payload.draws.sha256,
                    "scenario_id": payload.draws.scenario_id,
                },
                "base_currency": payload.base_currency,
                "snapshot_id": payload.snapshot_id,
                "options": payload.options,
                "run_id": payload.run_id,
            },
        }
        if self.tools is None:
            output = run_model(**arguments, registry=self.registry).model_dump(mode="json")
        else:
            output = self.tools.call("models", "run_model", **arguments)
        return ModelRunOutput.model_validate(output)
