from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from .common import Contract, Identifier, Number
from .evidence import Evidence
from .recommendation import Recommendation
from .result import CalculationResult, PortfolioResult


class NumberRef(Contract):
    value: Number
    metric_path: Identifier  # JSON Pointer into the run's metric tree, checked by V9.
    rounding: int = Field(strict=True, ge=0, le=12)


class Report(Contract):
    run_id: Identifier
    summary: str
    recommendations: list[Recommendation]
    assumptions: list[Evidence]
    sources: list[Evidence]
    numbers: list[NumberRef]
    # The results the text cites; approval signs them together with the text.
    results: list[CalculationResult] = Field(default_factory=list)
    portfolio: PortfolioResult | None = None
    mode: Literal["production", "demo"] = "production"
    approved_by: Identifier | None = None
    approved_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def approval(self):
        if (self.approved_by is None) != (self.approved_at is None):
            raise ValueError("Approval requires both author and timestamp")
        if self.approved_by == "demo:auto" and self.mode != "demo":
            raise ValueError("demo:auto is only allowed in demo reports")
        if any(e.kind != "expert_assumption" for e in self.assumptions):
            raise ValueError("assumptions must contain expert_assumption evidence")
        return self
