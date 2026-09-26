"""Result building blocks every model may use: quantiles, error intervals, applicability."""

from typing import Literal

from pydantic import Field, model_validator

from .common import (
    Contract,
    Identifier,
    NonNegative,
    Number,
    Unit,
)

ResultStatus = Literal["ok", "uncalibrated", "needs_review", "incomplete", "invalid"]


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


class ApplicabilityLimits(Contract):
    """The boundary of approved use (spec 0). Carried with every result, not assumed."""

    approved_uses: list[Identifier] = Field(default_factory=list)
    prohibited_uses: list[Identifier] = Field(default_factory=list)
    note: str = ""
