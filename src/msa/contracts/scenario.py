"""A confirmed scenario parameter: the distribution of one factor shock and where it enters.

A parameter moves one registered factor (``msa.plugin_sdk.FactorSpec``). A factor of the
``graph`` scope enters through a channel of the transmission graph and reaches each asset
through its sector; a factor of any other scope applies directly to the instruments whose
``key`` it names (a market index, a currency pair). A parameter without a factor replaces a
model input instead (the demand elasticity) and is reported as unmapped by models that do
not read it.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

Distribution = Literal["point", "triangular", "uniform", "truncated_normal"]
ParameterUnit = Literal["fraction", "days", "dimensionless", "log_return"]


class MacroParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Distribution
    value: float | None = None
    low: float | None = None
    mode: float | None = None
    high: float | None = None
    mean: float | None = None
    sigma: float | None = None
    unit: ParameterUnit
    #: A registered factor id, e.g. ``credit.revenue`` or ``equity.market``.
    factor: str | None = None
    #: Which instruments a direct factor applies to: ``MOEX``, ``USD/RUB``.
    key: str | None = None
    #: The graph channel a ``graph``-scope factor enters through.
    channel: str | None = None

    @model_validator(mode="after")
    def valid_distribution(self):
        if self.kind == "point":
            if self.value is None:
                raise ValueError("point requires value")
        elif self.kind == "triangular":
            if None in (self.low, self.mode, self.high):
                raise ValueError("triangular requires low, mode and high")
            if not self.low <= self.mode <= self.high or self.low >= self.high:
                raise ValueError("Require low <= mode <= high and low < high")
        elif self.kind == "uniform":
            if None in (self.low, self.high):
                raise ValueError("uniform requires low and high")
            if self.low >= self.high:
                raise ValueError("Require low < high")
        else:
            if None in (self.mean, self.sigma, self.low, self.high):
                raise ValueError("truncated_normal requires mean, sigma, low and high")
            if self.sigma <= 0:
                raise ValueError("Require sigma > 0")
            if self.low >= self.high:
                raise ValueError("Require low < high")
        return self


def central_value(parameter: MacroParameter) -> float:
    if parameter.kind == "point":
        return parameter.value
    if parameter.kind == "triangular":
        return parameter.mode
    if parameter.kind == "uniform":
        return (parameter.low + parameter.high) / 2
    return parameter.mean
