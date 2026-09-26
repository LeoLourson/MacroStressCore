"""Contracts of the credit plugin: the credit profile of a position and its result.

Monthly trajectories, covenant results, channel attribution, reverse stress and the risk
axes are the credit model's building blocks. ``RiskResult`` is the credit model's own result
(spec 20). It travels as the ``details`` of the platform's ``CalculationResult``, validated
against this schema.
"""

from calendar import monthrange
from datetime import date
from math import isclose, sqrt
from typing import Literal

from pydantic import Field, field_validator, model_validator

from msa.contracts.common import (
    Contract,
    Horizon,
    Identifier,
    NonNegative,
    Number,
    Positive,
    Probability,
    Seed,
    Sha256,
    Status,
    Unit,
    VersionStamp,
)
from msa.contracts.evidence import Evidence, Parameter
from msa.contracts.risk import ApplicabilityLimits, Interval, Quantiles, ResultStatus

RiskAxis = Literal["credit", "market", "liquidity", "covenant", "data_and_model"]
#: ``not_assessed``: no approved rule measured the axis; never read as a low risk.
Band = Literal["not_assessed", "low", "medium", "high", "critical"]


class MonthlySeries(Contract):
    """One named quantity over the horizon. ``None`` marks an undefined month."""

    name: Identifier
    unit: Unit
    values: list[Number | None] = Field(min_length=1)
    #: Quantity kind from spec 2.2; it decides what may be added to what.
    kind: Identifier = "flow_money"


class Trajectory(Contract):
    """A full monthly path under one scenario."""

    label: Literal["base", "stress"]
    horizon: Horizon
    month_ends: list[date] = Field(min_length=1)
    series: dict[Identifier, MonthlySeries] = Field(min_length=1)

    @model_validator(mode="after")
    def lengths_agree(self):
        if len(self.month_ends) != self.horizon:
            raise ValueError("month_ends must cover exactly the horizon")
        for previous, current in zip(self.month_ends, self.month_ends[1:], strict=False):
            expected_month = 1 if previous.month == 12 else previous.month + 1
            expected_year = previous.year + (previous.month == 12)
            if (current.year, current.month) != (expected_year, expected_month):
                raise ValueError("month_ends must be consecutive calendar months")
        for month_end in self.month_ends:
            if month_end.day != monthrange(month_end.year, month_end.month)[1]:
                raise ValueError("month_ends must contain calendar month ends")
        for name, item in self.series.items():
            if item.name != name:
                raise ValueError(f"series key {name} must match its name {item.name}")
            if len(item.values) != self.horizon:
                raise ValueError(f"series {name} must cover exactly the horizon")
        return self


class CovenantResult(Contract):
    covenant_id: Identifier
    metric: Identifier
    operator: Literal["ge", "gt", "le", "lt"]
    threshold: Number
    min_headroom: Number
    breach_month: int | None = None
    breach_date: date | None = None
    breach_probability: Probability
    cure_period_months: int = Field(default=0, ge=0)


class ShapleyContribution(Contract):
    channel: Identifier
    contribution: Number
    halfwidth: NonNegative = 0.0


class ReverseStressDirection(Contract):
    """Explicit stress direction, its norm and approved plausibility boundary."""

    components: dict[Identifier, Number] = Field(min_length=1)
    norm: Positive
    lambda_max: Positive = 5.0
    plausibility: Identifier

    @model_validator(mode="after")
    def norm_matches_components(self):
        calculated = sqrt(sum(value * value for value in self.components.values()))
        if not isclose(self.norm, calculated, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("direction norm must match its components")
        return self


class ReverseStressResult(Contract):
    target: Identifier
    status: Literal["found", "already_breached", "not_breached"]
    lambda_star: NonNegative | None = None
    #: Bracketing interval when the boundary is a jump rather than a root (spec 15).
    interval: tuple[Number, Number] | None = None
    direction: ReverseStressDirection
    shock: dict[Identifier, Number] | None = None
    metric_before: Number
    metric_after: Number
    continuous: bool = True
    later_crossings: list[tuple[Number, Number]] = Field(default_factory=list)
    flags: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def explicit_outcome(self):
        if self.status == "found":
            if self.continuous and (self.lambda_star is None or self.interval is not None):
                raise ValueError("a continuous crossing requires lambda_star and no interval")
            if not self.continuous and (self.lambda_star is not None or self.interval is None):
                raise ValueError("a discontinuous crossing requires an interval and no root")
            if self.shock is None:
                raise ValueError("found requires the stress shock")
        elif self.status == "already_breached":
            if self.lambda_star != 0 or self.interval is not None or not self.continuous:
                raise ValueError("already_breached requires lambda_star=0 and no interval")
            if self.shock is None:
                raise ValueError("already_breached requires the zero shock")
        elif self.lambda_star is not None or self.interval is not None or self.shock is not None:
            raise ValueError("not_breached has no root, interval or shock")

        boundaries = [self.interval, *self.later_crossings]
        for boundary in (item for item in boundaries if item is not None):
            low, high = boundary
            if not 0.0 <= low < high <= self.direction.lambda_max:
                raise ValueError("crossing intervals must be ordered within lambda_max")
        if self.lambda_star is not None and self.lambda_star > self.direction.lambda_max:
            raise ValueError("lambda_star must not exceed lambda_max")

        if self.shock is not None:
            if set(self.shock) != set(self.direction.components):
                raise ValueError("shock must contain every direction component")
            scale = self.lambda_star
            if scale is None and self.interval is not None:
                scale = self.interval[1]
            assert scale is not None
            for name, component in self.direction.components.items():
                if not isclose(self.shock[name], component * scale, rel_tol=1e-9, abs_tol=1e-12):
                    raise ValueError("shock must equal lambda times the direction")
        return self


class AxisSummary(Contract):
    axis: RiskAxis
    band: Band = "not_assessed"
    reason: str = ""
    recommendation: str = ""
    measures: dict[Identifier, Number | None] = Field(default_factory=dict)
    flags: list[Identifier] = Field(default_factory=list)


class Covenant(Contract):
    covenant_id: Identifier
    metric: Identifier
    operator: Literal["ge", "le"]
    threshold: Number
    unit: Unit
    test_dates: list[date] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class Collateral(Contract):
    kind: Identifier
    value: NonNegative
    coverage_ratio: NonNegative  # May exceed 1 (CASE-OVERCOLLATERALISED).
    haircut: Probability
    evidence: list[Evidence] = Field(min_length=1)


class CreditProfile(Contract):
    """One credit position as the model reads it: the borrower, the exposure and the inputs.

    The credit plugin assembles it from the party, the instrument, the position and the
    snapshot's statement; it is internal to the plugin and never crosses the platform.
    """

    asset_id: Identifier
    okved: Identifier
    #: A credit instrument type; its family declares the financials it reads.
    asset_type: Identifier
    ead: Positive
    lgd: Probability
    financials: dict[Identifier, Parameter]
    dq: Probability
    covenants: list[Covenant]
    proxy_peer_ids: list[Identifier]
    collateral: list[Collateral]
    ccf: Probability
    import_share: Probability
    currency: Literal["RUB"] = "RUB"
    money_unit: Literal["RUB_million"] = "RUB_million"
    # Sources for numeric fields outside financials/covenants/collateral.
    field_evidence: dict[Identifier, list[Evidence]]
    driver_elasticity: dict[Identifier, Number] = Field(default_factory=dict)
    status: Status = "ok"
    flags: list[Identifier] = Field(default_factory=list)

    @field_validator("asset_type")
    @classmethod
    def registered_type(cls, value):
        from .families import asset_types

        if value not in asset_types():
            raise ValueError(
                f"unknown asset type {value!r}; registered: {', '.join(asset_types())}"
            )
        return value

    @property
    def exposure(self) -> float:
        """The amount at risk: EAD times the share of it drawn by default (CCF)."""
        return float(self.ead) * float(self.ccf)

    @model_validator(mode="after")
    def numeric_sources(self):
        for name in ("ead", "lgd", "dq", "ccf", "import_share"):
            if not self.field_evidence.get(name):
                raise ValueError(f"field_evidence.{name} requires a source")
        if not self.financials and not self.proxy_peer_ids and self.status != "needs_review":
            raise ValueError("Missing financials and peers requires needs_review")
        if self.status == "needs_review" and not self.flags:
            raise ValueError("needs_review requires a reason in flags")
        return self


class CreditResult(Contract):
    """Credit axis. ``pd`` stays empty until the model is calibrated (spec 7.1)."""

    calibrated: bool
    segment_id: Identifier
    risk_score: Probability | None = None
    pd: Probability | None = None
    lgd: Probability | None = None
    lgd_applicable: bool = True
    ead: NonNegative | None = None
    expected_loss: NonNegative | None = None
    delta_expected_loss: Number | None = None

    @model_validator(mode="after")
    def calibration_gate(self):
        if self.calibrated and self.pd is None:
            raise ValueError("a calibrated credit result must report a PD")
        if self.calibrated and self.risk_score is not None:
            raise ValueError("a calibrated credit result reports PD, not risk_score")
        if not self.calibrated:
            if self.pd is not None:
                raise ValueError("an uncalibrated result must not report a PD")
            if self.risk_score is None:
                raise ValueError("an uncalibrated result must report a risk_score")
            if self.expected_loss is not None:
                raise ValueError("expected loss requires a calibrated PD")
            if self.delta_expected_loss is not None:
                raise ValueError("delta expected loss requires a calibrated PD")
        if not self.lgd_applicable and self.lgd is not None:
            raise ValueError("an inapplicable LGD must be omitted")
        if self.expected_loss is not None:
            if self.pd is None or self.lgd is None or self.ead is None:
                raise ValueError("expected loss requires PD, LGD and EAD")
            if not self.lgd_applicable:
                raise ValueError("expected loss requires an applicable LGD")
        if self.delta_expected_loss is not None and self.expected_loss is None:
            raise ValueError("delta expected loss requires expected loss")
        return self


class LiquidityResult(Contract):
    min_cash_headroom: Number
    max_funding_gap: NonNegative
    limit_excess: NonNegative = 0.0


class MarketResult(Contract):
    base_price: Number | None = None
    stress_price: Number | None = None
    price_change: Number | None = None
    duration: Number | None = None
    convexity: Number | None = None
    #: Gap between the full reprice and the local approximation (spec 10.2).
    approximation_gap: Number | None = None


class RiskResult(Contract):
    """``run_asset(input, scenario_set, model_registry, seed) -> RiskResult`` (spec 20)."""

    asset_id: Identifier
    as_of: date
    horizon: Horizon
    status: ResultStatus
    model_id: Identifier
    seed: Seed
    versions: VersionStamp
    model_versions: dict[Identifier, Identifier] = Field(min_length=1)
    macro_draws_sha256: Sha256 | None = None
    input_sources: dict[Identifier, list[Identifier]] = Field(default_factory=dict)

    base: Trajectory | None = None
    stress: Trajectory | None = None

    credit: CreditResult | None = None
    market: MarketResult | None = None
    liquidity: LiquidityResult | None = None
    covenants: list[CovenantResult] = Field(default_factory=list)

    quantiles: dict[Identifier, Quantiles] = Field(default_factory=dict)
    intervals: dict[Identifier, Interval] = Field(default_factory=dict)
    shapley: list[ShapleyContribution] = Field(default_factory=list)
    reverse_stress: list[ReverseStressResult] = Field(default_factory=list)
    axes: list[AxisSummary] = Field(default_factory=list)

    flags: list[Identifier] = Field(default_factory=list)
    coverage: dict[Identifier, Probability] = Field(default_factory=dict)
    limits: ApplicabilityLimits = Field(default_factory=ApplicabilityLimits)
    # Joint-realisation losses used only for portfolio aggregation.  Scores are never
    # smuggled into this field: it is present only after the PD/LGD/EAD gate has passed.
    aggregation_draws: list[Number] | None = Field(default=None, min_length=1, exclude=True)

    @model_validator(mode="after")
    def status_consistency(self):
        if self.status == "ok" and (self.base is None or self.stress is None):
            raise ValueError("ok requires both a base and a stress trajectory")
        if self.status in ("needs_review", "incomplete", "invalid") and not self.flags:
            raise ValueError(f"{self.status} requires a reason in flags")
        if self.status == "uncalibrated" and (self.credit is None or self.credit.calibrated):
            raise ValueError("uncalibrated requires an uncalibrated credit result")
        if self.status == "ok" and self.credit is not None and not self.credit.calibrated:
            raise ValueError("ok contradicts an uncalibrated credit result")
        if self.aggregation_draws is not None:
            if self.credit is None or not self.credit.calibrated:
                raise ValueError("aggregation draws require calibrated credit loss")
            if "delta_expected_loss" not in self.quantiles:
                raise ValueError("aggregation draws require delta_expected_loss quantiles")
        if self.versions.macro_draws_sha256 != self.macro_draws_sha256:
            raise ValueError("Version stamp and result macro hashes must agree")

        trajectories = (("base", self.base), ("stress", self.stress))
        for label, trajectory in trajectories:
            if trajectory is None:
                continue
            if trajectory.label != label:
                raise ValueError(f"{label} trajectory must have label={label}")
            if trajectory.horizon != self.horizon:
                raise ValueError(f"{label} trajectory horizon must match the result")
            if trajectory.month_ends[0] != _next_month_end(self.as_of):
                raise ValueError(f"{label} trajectory must start after as_of")
        if self.base is not None and self.stress is not None:
            if self.base.month_ends != self.stress.month_ends:
                raise ValueError("base and stress trajectories must share the calendar")
            if set(self.base.series) != set(self.stress.series):
                raise ValueError("base and stress trajectories must contain the same series")
            for name, base_series in self.base.series.items():
                stress_series = self.stress.series[name]
                if (base_series.unit, base_series.kind) != (
                    stress_series.unit,
                    stress_series.kind,
                ):
                    raise ValueError(f"base and stress series {name} must have the same type")
        return self


def _next_month_end(as_of: date) -> date:
    year = as_of.year + (as_of.month == 12)
    month = 1 if as_of.month == 12 else as_of.month + 1
    return date(year, month, monthrange(year, month)[1])
