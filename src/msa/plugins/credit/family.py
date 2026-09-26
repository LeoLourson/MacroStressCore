"""A credit family: one monthly model of a borrower, shared by its instrument types.

A family declares everything Track A and the platform need to know about its types:

- the inputs it reads, each with its unit, Russian label, whether it is required, the
  default used when it is absent, and where it comes from: the borrower's statement in
  the data snapshot, the instrument's terms, or market data of the snapshot. A default
  that stands in for missing data is an assumption and raises its flag; nothing silently
  becomes zero;
- the monthly series it produces, the metrics covenants may be written on, and the metrics
  whose horizon-end P5/P50/P95 the result reports;
- the PD segment it belongs to by default;
- ``evaluate``: the monthly model under a set of driver shocks.

Track A (``track_a``) is family-agnostic: scenario draws, transmission, the PD score,
expected loss, covenants, Shapley and reverse stress work the same for every family.
"""

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Literal

import numpy as np

#: Drivers every family receives, as monthly relative changes (``working_capital`` in days and
#: ``interest`` in annual rate points are additive). Each is the registered factor
#: ``credit.<driver>`` of the ``graph`` scope.
DRIVERS = ("revenue", "cogs", "logistics", "working_capital", "interest", "capex", "fx")
FACTOR_PREFIX = "credit."


def factor_id(driver: str) -> str:
    return FACTOR_PREFIX + driver


def driver_of(factor: str | None) -> str | None:
    """The driver a credit factor moves; ``None`` for a factor of another family."""
    if factor is None or not factor.startswith(FACTOR_PREFIX):
        return None
    name = factor.removeprefix(FACTOR_PREFIX)
    return name if name in DRIVERS else None


#: Liquidity metrics the engine reads when a model provides them.
LIQUIDITY_METRICS = ("cash_headroom", "funding_gap", "limit_excess")


class MissingInput(ValueError):
    """A required input is absent: the asset cannot be calculated without inventing it."""


Source = Literal["statement", "terms", "market"]


@dataclass(frozen=True)
class InputField:
    name: str
    unit: str
    label: str
    required: bool = False
    #: Value used when the profile does not carry the field. ``None``: the model reads the
    #: absence itself (``Inputs.get``) or, for a required field, cannot run.
    default: float | None = None
    #: Flag raised when the default is used because data is missing (an assumption).
    assumption: str | None = None
    hint: str = ""
    #: Shown folded in the portfolio editor.
    advanced: bool = False
    #: Inclusive bounds of a meaningful value; fractions are always within [0, 1] as well.
    minimum: float | None = None
    maximum: float | None = None
    #: ``statement``: the borrower's reported figures in the data snapshot; ``terms``: the
    #: instrument's contractual terms; ``market``: a snapshot quote (see ``market``).
    source: Source = "statement"
    #: For a market input: (item kind, subject with ``{currency}``, value name).
    market: tuple[str, str, str] | None = None

    def bounds(self) -> tuple[float | None, float | None]:
        """Declared bounds intersected with the range of the unit (audit finding A4)."""
        low, high = self.minimum, self.maximum
        if self.unit == "fraction":
            low = 0.0 if low is None else max(0.0, low)
            high = 1.0 if high is None else min(1.0, high)
        return low, high


@dataclass(frozen=True)
class Series:
    """A monthly quantity the model reports for the base and stress trajectories."""

    name: str
    label: str
    unit: str = "RUB_million"
    #: What may be added to what (spec 2.2): flow_money, stock_money, ratio, probability.
    kind: str = "flow_money"


@dataclass(frozen=True)
class CovenantMetric:
    """A metric a covenant may be written on, with the editor's default test."""

    name: str
    label: str
    operator: str = "ge"
    threshold: float = 1.0


@dataclass
class Evaluation:
    """One scenario through the model. Arrays are ``lead + (H,)``; ``lead`` is the draw axes."""

    #: Every declared series.
    series: dict[str, np.ndarray]
    #: Paths covenants, decision quantiles and the liquidity axis read.
    metrics: dict[str, np.ndarray]
    #: PD model features by month; their names must match the calibration's coefficients.
    features: dict[str, np.ndarray]
    flags: list[str] = field(default_factory=list)


class Inputs:
    """The profile's financials read against the family's declared inputs."""

    def __init__(self, profile, fields: tuple[InputField, ...], flags: list[str]):
        self._fields = {item.name: item for item in fields}
        self._values = {name: float(item.value) for name, item in profile.financials.items()}
        self._flags = flags

    def __contains__(self, name: str) -> bool:
        self._field(name)
        return name in self._values

    def __getitem__(self, name: str) -> float:
        field = self._field(name)
        if name in self._values:
            return self._values[name]
        if field.default is None:
            raise MissingInput(f"{name} is required and absent")
        if field.assumption and field.assumption not in self._flags:
            self._flags.append(field.assumption)
        return field.default

    def get(self, name: str) -> float | None:
        """The value, or ``None`` when absent; declared defaults do not apply."""
        self._field(name)
        return self._values.get(name)

    def _field(self, name: str) -> InputField:
        try:
            return self._fields[name]
        except KeyError:
            raise KeyError(f"{name} is not a declared input of this credit family") from None


class CreditFamily(ABC):
    #: instrument type -> its name in Russian. One family may serve several contract types.
    types: dict[str, str]
    #: PD segment of the calibration registry, unless the registry maps the asset otherwise.
    segment: str
    fields: tuple[InputField, ...]
    #: Inputs whose presence measures disclosure for the data-quality score (TZ 3.3).
    disclosure: tuple[str, ...]
    series: tuple[Series, ...]
    covenant_metrics: tuple[CovenantMetric, ...] = ()
    #: Metrics whose horizon-end P5/P50/P95 the result reports and the advisory rules read.
    decision_metrics: tuple[str, ...] = ()
    #: Whether LGD x EAD is the loss of this asset type.
    lgd_applicable: bool = True
    #: Whether the model reprices a market position (``market``).
    has_market: bool = False
    #: Flags of this model that send a result to manual review (spec 19): simplifications
    #: and assumptions that a reviewer has to accept before the number is used.
    review_flags: frozenset[str] = frozenset()

    @property
    def required(self) -> frozenset[str]:
        return frozenset(item.name for item in self.fields if item.required)

    #: The platform model that calculates this family.
    model_id: str = ""

    def inputs(self, profile, flags: list[str]) -> Inputs:
        return Inputs(profile, self.fields, flags)

    def problems(self, financials) -> list[tuple[str, str]]:
        """Why the profile's financials cannot be read by this model: (field, message) pairs."""
        declared = {item.name: item for item in self.fields}
        problems = []
        for name, parameter in financials.items():
            item = declared.get(name)
            if item is None:
                problems.append((name, f"{name} is not an input of this asset type"))
                continue
            unit = parameter.get("unit") if isinstance(parameter, dict) else parameter.unit
            value = parameter.get("value") if isinstance(parameter, dict) else parameter.value
            if unit != item.unit:
                problems.append((name, f"{name} is measured in {item.unit}, not {unit}"))
            low, high = item.bounds()
            if (low is not None and value < low) or (high is not None and value > high):
                problems.append((name, f"{name} must lie within [{low}, {high}]"))
        return problems

    def missing(self, financials) -> list[str]:
        return sorted(self.required - set(financials))

    def unit(self, name: str) -> str:
        return next((item.unit for item in self.series if item.name == name), "ratio")

    @abstractmethod
    def evaluate(self, inputs: Inputs, calendar, drivers: dict[str, np.ndarray]) -> Evaluation:
        """The monthly model under the given driver shocks (zero shocks give the base)."""

    def market(self, profile, inputs, registry, flags, pd):
        """Central market repricing and the position change per realisation, if any.

        ``pd`` is ``(base, stress, realised)`` at the horizon end when the PD is calibrated.
        """
        return None, None

    def fields_from(self, source: str) -> tuple[InputField, ...]:
        return tuple(item for item in self.fields if item.source == source)

    def describe(self) -> dict:
        """What the catalog serves about the family: its inputs, series and covenant metrics."""
        return {
            "segment": self.segment,
            "fields": [asdict(item) for item in self.fields],
            "series": [asdict(item) for item in self.series],
            "covenant_metrics": [asdict(item) for item in self.covenant_metrics],
            "decision_metrics": list(self.decision_metrics),
        }


def compound(*changes) -> np.ndarray:
    """Relative changes applied one after another: (1 + a)(1 + b) - 1."""
    arrays = [np.asarray(value, dtype=float) for value in changes]
    result = np.ones(np.broadcast_shapes(*(value.shape for value in arrays)))
    for value in arrays:
        result = result * (1.0 + value)
    return result - 1.0
