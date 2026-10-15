"""The catalog of registered calculation models that ``mcp-models`` serves.

``run_model`` calculates one prepared position with any model a plugin registered. The
payload carries the prepared inputs, the model's own verdict on them and the run's scenario
set as a specification; the realisations are regenerated deterministically from it and
must hash to the run's shared matrix, so every position of a run reads the same joint
scenarios wherever it is calculated. The result is stamped with the model version and the
hash of the code that produced it; the contributions' realisations travel beside the
result, since they are never persisted.
"""

from datetime import date
from hashlib import sha256
from inspect import getsourcefile
from pathlib import Path

from pydantic import Field, JsonValue

from msa.contracts.common import Contract, Horizon, Identifier, Number, Seed, Sha256
from msa.contracts.graph import TransmissionGraph
from msa.contracts.result import CalculationResult
from msa.platform.registry import registry as current_registry
from msa.plugin_sdk.model import CalculationContext, Diagnostics, PreparedInputs
from msa.version import code_sha256

from .dispatch import calculate
from .scenario_set import Realisations, ScenarioSet


class ScenarioPayload(Contract):
    """The run's approved scenario set, as a specification any process can regenerate."""

    spec: dict[str, JsonValue]
    seed: Seed
    as_of: date
    horizon: Horizon
    graph: TransmissionGraph | None = None
    factor_versions: dict[Identifier, Identifier] = Field(default_factory=dict)
    #: The hash of the shared matrix the run recorded before any calculation.
    macro_draws_sha256: Sha256
    scenario_id: Sha256


class ModelRunInput(Contract):
    prepared: PreparedInputs
    diagnostics: Diagnostics
    scenario: ScenarioPayload
    base_currency: Identifier = "RUB"
    snapshot_id: Identifier
    options: dict[str, JsonValue] = Field(default_factory=dict)
    run_id: Identifier | None = None


class ModelRunOutput(Contract):
    result: CalculationResult
    #: slice id -> loss realisations in the shared order; for the aggregator only.
    draws: dict[Identifier, list[Number]] = Field(default_factory=dict)
    code_sha256: Sha256


class ScenarioMismatch(ValueError):
    """The regenerated realisations differ from the run's shared matrix."""


def realisations(payload: ScenarioPayload) -> tuple[ScenarioSet, Realisations]:
    scenario_set = ScenarioSet.from_spec(payload.spec)
    view = Realisations(
        scenario_set=scenario_set,
        seed=payload.seed,
        as_of=payload.as_of,
        horizon=payload.horizon,
        graph=payload.graph,
        factor_versions=payload.factor_versions,
    )
    if view.macro_draws_sha256 != payload.macro_draws_sha256:
        raise ScenarioMismatch("the regenerated scenario matrix differs from the run's")
    if view.scenario_id != payload.scenario_id:
        raise ScenarioMismatch("the scenario set identity differs from the run's")
    return scenario_set, view


def model_code_hash(model) -> str:
    """The package hash with the model's own source: what exactly produced a number."""
    source = getsourcefile(type(model))
    if source is None:
        raise ValueError("A registered model must have an inspectable Python source file")
    return sha256(code_sha256().encode() + Path(source).read_bytes()).hexdigest()


def run_model(model_id: str, payload: dict | ModelRunInput, *, registry=None) -> ModelRunOutput:
    registry = registry or current_registry()
    model = registry.model(model_id)
    run = payload if isinstance(payload, ModelRunInput) else ModelRunInput.model_validate(payload)
    if run.prepared.model_id != model_id:
        raise ValueError(f"the inputs were prepared for {run.prepared.model_id}, not {model_id}")
    scenario_set, view = realisations(run.scenario)
    context = CalculationContext(
        as_of=run.scenario.as_of,
        horizon=run.scenario.horizon,
        seed=run.scenario.seed,
        base_currency=run.base_currency,
        scenario=view,
        snapshot_id=run.snapshot_id,
        scenario_set=scenario_set,
        options=run.options,
        run_id=run.run_id,
    )
    result = calculate(run.prepared, run.diagnostics, context, registry)
    draws = {c.slice_id: list(c.draws) for c in result.contributions if c.draws is not None}
    digest = model_code_hash(model)
    return ModelRunOutput(
        result=result.model_copy(update={"code_sha256": digest}),
        draws=draws,
        code_sha256=digest,
    )


def list_models(*, registry=None) -> list[dict]:
    registry = registry or current_registry()
    return [describe_model(model_id, registry=registry) for model_id in sorted(registry.models)]


def describe_model(model_id: str, *, registry=None) -> dict:
    registry = registry or current_registry()
    model = registry.model(model_id)
    plugin = registry.plugin_of(model_id)
    metrics = {
        metric_id: {
            "label": registry.metrics[metric_id].label,
            "unit": registry.metrics[metric_id].unit,
            "kind": registry.metrics[metric_id].kind,
            "direction": registry.metrics[metric_id].direction,
            "period": registry.metrics[metric_id].period,
        }
        for metric_id in model.metrics
    }
    return {
        **model.describe(),
        "plugin_id": plugin.plugin_id,
        "plugin_version": plugin.version,
        "code_sha256": model_code_hash(model),
        "metric_specs": metrics,
        "input_schema": ModelRunInput.model_json_schema(),
    }
