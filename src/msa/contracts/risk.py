"""Result building blocks shared by every family: quantiles, series, covenants, attribution."""

from calendar import monthrange
from datetime import date
from math import isclose, sqrt
from typing import Literal

from pydantic import Field, model_validator

from .common import (
    Contract,
    Horizon,
    Identifier,
    NonNegative,
    Number,
    Positive,
    Probability,
    Unit,
)

ResultStatus = Literal["ok", "uncalibrated", "needs_review", "incomplete", "invalid"]
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


class Interval(Contract):
    """A reported quantity with its numerical error interval (spec 13.3)."""

    name: Identifier
    unit: Unit
    mean: Number
    standard_error: NonNegative
    halfwidth: NonNegative
    replicates: int = Field(strict=True, ge=8)
    within_tolerance: bool


class Quantiles(Contract):
    """P5/P50/P95 and ES95 for one explicitly named quantity (spec 20)."""

    name: Identifier
    unit: Unit
    p05: Number
    p50: Number
    p95: Number
    es95: Number | None = None

    @model_validator(mode="after")
    def ordered(self):
        if not self.p05 <= self.p50 <= self.p95:
            raise ValueError("Require p05 <= p50 <= p95")
        if self.es95 is not None and self.es95 < self.p95:
            raise ValueError("ES95 cannot fall below P95")
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


class ApplicabilityLimits(Contract):
    """The boundary of approved use (spec 0). Carried with every result, not assumed."""

    approved_uses: list[Identifier] = Field(default_factory=list)
    prohibited_uses: list[Identifier] = Field(default_factory=list)
    note: str = ""
