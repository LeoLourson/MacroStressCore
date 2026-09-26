"""Helpers that fill the identity of a result, so a model states only what it calculated."""

import numpy as np

from msa.contracts.result import CalculationResult, MetricValue
from msa.contracts.risk import Quantiles
from msa.version import code_sha256

from .model import CalculationContext, CalculationModel, PreparedInputs


def envelope(
    prepared: PreparedInputs,
    context: CalculationContext,
    model: CalculationModel,
    *,
    plugin_id: str,
    plugin_version: str,
    **fields,
) -> CalculationResult:
    """A completed result of ``model`` for the prepared position under ``context``."""
    position = prepared.context
    values = {
        "position_id": position.position_id,
        "instrument_id": position.instrument.instrument_id,
        "instrument_type": position.instrument.instrument_type,
        "plugin_id": plugin_id,
        "plugin_version": plugin_version,
        "model_id": model.model_id,
        "model_version": model.version,
        "as_of": context.as_of,
        "horizon": context.horizon,
        "seed": context.seed,
        "base_currency": context.base_currency,
        "scenario_id": context.scenario.scenario_id,
        "snapshot_id": context.snapshot_id,
        "macro_draws_sha256": context.scenario.macro_draws_sha256,
        "execution": "completed",
        "code_sha256": code_sha256(),
    }
    values.update(fields)
    return CalculationResult(**values)


def quantiles(name: str, unit: str, draws, *, tail: bool = False) -> Quantiles:
    """P5/P50/P95 of realisations; ``tail`` adds ES95 for a loss (higher is worse)."""
    from msa.engine.portfolio import expected_shortfall

    values = np.asarray(draws, dtype=float).reshape(-1)
    p05, p50, p95 = np.percentile(values, [5, 50, 95], method="linear")
    return Quantiles(
        name=name,
        unit=unit,
        p05=float(p05),
        p50=float(p50),
        p95=float(p95),
        es95=max(expected_shortfall(values), float(p95)) if tail else None,
    )


def distribution(metric_id: str, unit: str, draws, *, value=None, tail=False) -> MetricValue:
    return MetricValue(
        metric_id=metric_id,
        unit=unit,
        value=value,
        quantiles=quantiles(metric_id, unit, draws, tail=tail),
    )


def scalar(metric_id: str, unit: str, value: float) -> MetricValue:
    return MetricValue(metric_id=metric_id, unit=unit, value=float(value))
