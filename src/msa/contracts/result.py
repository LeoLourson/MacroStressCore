"""The common envelope of every calculation and the portfolio slices built from them.

``CalculationResult`` is what any model returns for one position: who and what was
calculated, with which model, scenario and snapshot; whether it ran, whether the method
applies and how good the data were — three separate things; typed metrics with units;
the plugin's own ``details`` (validated by the plugin's schema); sources, assumptions and
limits; and the contributions it makes to portfolio slices.

A portfolio slice (``SliceResult``) adds up one measure with one economic meaning — the
credit expected-loss change, the market P&L — inside every joint realisation before any
quantile is taken. Different slices are never added to each other.
"""

from datetime import date
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from .common import (
    Contract,
    Currency,
    Horizon,
    Identifier,
    NonNegative,
    Number,
    Probability,
    Seed,
    Sha256,
    Unit,
)
from .evidence import Evidence
from .risk import ApplicabilityLimits, Quantiles

Execution = Literal["completed", "not_run", "failed"]
Applicability = Literal["applicable", "limited", "not_applicable"]
ResultStatus = Literal["ok", "uncalibrated", "needs_review", "incomplete", "invalid"]
Severity = Literal["info", "warning", "error"]


class Diagnostic(Contract):
    """One finding about the inputs or the output of a model, with a machine code."""

    code: Identifier
    severity: Severity
    message: str = ""
    #: JSON Pointer into the prepared inputs or the result.
    path: str = ""


class DataQuality(Contract):
    """How far the data can be trusted, apart from whether the calculation ran."""

    score: Probability | None = None
    level: Literal["high", "medium", "low", "unknown"] = "unknown"
    issues: list[Identifier] = Field(default_factory=list)


class MetricValue(Contract):
    """One metric of a result. Its label, direction and aggregation live in the catalog."""

    metric_id: Identifier
    unit: Unit
    #: A deterministic value: the central scenario, or a quantity that does not vary.
    value: Number | None = None
    #: P5/P50/P95 over the run's joint realisations, when the metric is a distribution.
    quantiles: Quantiles | None = None

    @model_validator(mode="after")
    def has_a_number(self):
        if self.value is None and self.quantiles is None:
            raise ValueError(f"metric {self.metric_id} carries neither a value nor quantiles")
        if self.quantiles is not None and self.quantiles.unit != self.unit:
            raise ValueError(f"metric {self.metric_id} quantiles are in another unit")
        return self


class ArtifactRef(Contract):
    """A stored calculation artifact the result refers to instead of carrying it."""

    kind: Identifier
    ref: Identifier
    sha256: Sha256 | None = None


class AggregationContribution(Contract):
    """What one position adds to one portfolio slice, in the run's realisation order.

    ``draws`` are losses (a gain is negative) in the slice's unit; they travel with the
    calculation to the aggregator and are never persisted.
    """

    slice_id: Identifier
    measure: Identifier
    unit: Unit
    horizon: Horizon
    scenario_id: Sha256
    #: Size of the position on the slice's coverage basis (EAD, market value).
    exposure: NonNegative | None
    exposure_basis: Identifier
    #: ``included`` enters the slice; ``admitted:<rule>`` enters under an approved rule
    #: with disclosure; ``excluded:<reason>`` stays out and is reported as a gap.
    admission: Identifier = "included"
    draws: list[Number] | None = Field(default=None, min_length=1, exclude=True)

    @property
    def enters(self) -> bool:
        return not self.admission.startswith("excluded")


class CalculationResult(Contract):
    """``calculate(prepared_inputs, calculation_context) -> CalculationResult``."""

    position_id: Identifier
    instrument_id: Identifier
    instrument_type: Identifier
    plugin_id: Identifier
    plugin_version: Identifier
    model_id: Identifier
    model_version: Identifier
    as_of: date
    horizon: Horizon
    seed: Seed
    base_currency: Currency = "RUB"
    #: Identity of the approved scenario set and the data snapshot the numbers rest on.
    scenario_id: Sha256 | None = None
    snapshot_id: Identifier | None = None
    macro_draws_sha256: Sha256 | None = None

    execution: Execution
    applicability: Applicability = "applicable"
    data_quality: DataQuality = Field(default_factory=DataQuality)
    #: The summary the aggregation and the report act on.
    status: ResultStatus

    metrics: dict[Identifier, MetricValue] = Field(default_factory=dict)
    #: The plugin's own result, valid against ``details_schema``.
    details: dict[str, JsonValue] = Field(default_factory=dict)
    details_schema: Identifier | None = None

    #: Input name -> source ids it was read from.
    input_sources: dict[Identifier, list[Identifier]] = Field(default_factory=dict)
    sources: list[Evidence] = Field(default_factory=list)
    #: Flags of declared defaults that stood in for missing data.
    assumptions: list[Identifier] = Field(default_factory=list)
    flags: list[Identifier] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    limits: ApplicabilityLimits = Field(default_factory=ApplicabilityLimits)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    contributions: list[AggregationContribution] = Field(default_factory=list)
    model_versions: dict[Identifier, Identifier] = Field(default_factory=dict)
    code_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def consistent(self):
        for key, metric in self.metrics.items():
            if key != metric.metric_id:
                raise ValueError(f"metric key {key} differs from its id {metric.metric_id}")
        if self.execution != "completed":
            if self.metrics or self.contributions:
                raise ValueError("a calculation that did not complete reports no numbers")
            if self.status == "ok":
                raise ValueError("a calculation that did not complete cannot be ok")
        if self.status in ("needs_review", "incomplete", "invalid") and not (
            self.flags or any(d.severity == "error" for d in self.diagnostics)
        ):
            raise ValueError(f"{self.status} requires a reason in flags or diagnostics")
        slices = [item.slice_id for item in self.contributions]
        if len(slices) != len(set(slices)):
            raise ValueError("a result contributes to each slice at most once")
        for item in self.contributions:
            if item.horizon != self.horizon or item.scenario_id != self.scenario_id:
                raise ValueError("a contribution must share the result's horizon and scenario")
        return self


class ExcludedPosition(Contract):
    position_id: Identifier
    status: Identifier
    reason: str


class PositionContribution(Contract):
    position_id: Identifier
    mean_loss: Number
    expected_shortfall_contribution: Number
    p95_standalone: Number


class Coverage(Contract):
    basis: Identifier
    #: Share of the slice's exposure whose numbers entered the slice.
    covered_share: Probability
    limit: Probability
    #: Positions of the slice whose exposure could not be measured.
    unknown_exposure: list[Identifier] = Field(default_factory=list)


class SliceResult(Contract):
    """One portfolio slice: losses summed inside each joint realisation, then quantiles."""

    slice_id: Identifier
    measure: Identifier
    unit: Unit
    status: Literal["ok", "needs_review", "incomplete", "invalid"]
    loss_quantiles: Quantiles | None = None
    mean_loss: Number | None = None
    value_at_risk_95: Number | None = None
    expected_shortfall_95: Number | None = None
    coverage: Coverage
    herfindahl: NonNegative
    included: list[Identifier] = Field(default_factory=list)
    excluded: list[ExcludedPosition] = Field(default_factory=list)
    contributions: list[PositionContribution] = Field(default_factory=list)
    # Descriptive statistic only; consumers must not label it the slice P95.
    sum_of_individual_p95: Number | None = None
    flags: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def completeness_is_explicit(self):
        if self.included and self.loss_quantiles is None:
            raise ValueError("included positions require slice loss quantiles")
        if not self.included and self.loss_quantiles is not None:
            raise ValueError("slice quantiles require at least one included position")
        numeric = (
            self.mean_loss,
            self.value_at_risk_95,
            self.expected_shortfall_95,
            self.sum_of_individual_p95,
        )
        if self.loss_quantiles is None and any(value is not None for value in numeric):
            raise ValueError("an empty slice must not report loss statistics")
        if self.loss_quantiles is not None:
            if self.loss_quantiles.unit != self.unit:
                raise ValueError("slice quantiles must be in the slice unit")
            if self.loss_quantiles.es95 != self.expected_shortfall_95:
                raise ValueError("loss quantile ES95 must match expected_shortfall_95")
        uncovered = 1.0 - self.coverage.covered_share
        if (
            uncovered > self.coverage.limit or self.coverage.unknown_exposure
        ) and self.status != "incomplete":
            raise ValueError("coverage below the approved limit requires incomplete status")
        if self.status in {"needs_review", "incomplete", "invalid"} and not self.flags:
            raise ValueError(f"{self.status} requires a reason in flags")
        if {item.position_id for item in self.excluded}.intersection(self.included):
            raise ValueError("a position cannot be both included and excluded")
        return self


class PortfolioResult(Contract):
    """Every slice of one run, on one scenario set, in the portfolio's base currency."""

    run_id: Identifier
    as_of: date
    horizon: Horizon
    seed: Seed
    base_currency: Currency = "RUB"
    scenario_id: Sha256
    macro_draws_sha256: Sha256
    slices: dict[Identifier, SliceResult] = Field(default_factory=dict)
    #: Positions of the run that entered no slice, with the reason.
    not_aggregated: list[ExcludedPosition] = Field(default_factory=list)
    model_versions: dict[Identifier, Identifier] = Field(default_factory=dict)
    status: Literal["ok", "needs_review", "incomplete", "invalid"]
    flags: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def keyed(self):
        for key, item in self.slices.items():
            if key != item.slice_id:
                raise ValueError(f"slice key {key} differs from its id {item.slice_id}")
        if self.status in {"needs_review", "incomplete", "invalid"} and not (
            self.flags or any(item.flags for item in self.slices.values())
        ):
            raise ValueError(f"{self.status} requires a reason in flags")
        return self
