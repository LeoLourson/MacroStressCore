"""The calculation model interface and what flows through it.

::

    requirements(position, options) -> DataRequirements
    validate(prepared_inputs)       -> Diagnostics
    calculate(prepared_inputs, calculation_context) -> CalculationResult

``requirements`` says what the model needs from the data snapshot and which factors it is
sensitive to. The platform resolves the data (``PreparedInputs``) — a model never reads a
database, the network or an LLM. ``validate`` judges the prepared inputs; an ``error`` stops
the calculation and the position stays in the run with its reason. ``calculate`` is a pure
function of the prepared inputs and the context: the approved scenario set, dates, seed and
versions. It reads joint realisations from the context and never draws random numbers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Protocol

import numpy as np
from pydantic import Field, JsonValue, model_validator

from msa.contracts.common import Contract, Horizon, Identifier, NonNegative
from msa.contracts.domain import PositionContext
from msa.contracts.graph import TransmissionGraph
from msa.contracts.result import CalculationResult, DataQuality, Diagnostic
from msa.contracts.risk import ApplicabilityLimits
from msa.contracts.scenario import MacroParameter
from msa.contracts.snapshot import SnapshotItem


class DataRequirement(Contract):
    """Snapshot items a model reads, by kind and subject, dated no later than ``as_of``."""

    #: Name of the resolved data in ``PreparedInputs.data``.
    key: Identifier
    kind: Identifier
    #: One subject: a party, an instrument, a currency pair, a curve.
    subject: Identifier | None = None
    #: Several explicit subjects (configured peers).
    subjects: list[Identifier] | None = None
    #: Items of other parties whose activity (OKVED) matches this party's, deepest first.
    peers_of: Identifier | None = None
    required: bool = True
    #: A list of items rather than the latest one.
    many: bool = False
    limit: int = Field(default=10, ge=1, le=100)
    #: Among items of the same date, prefer these values of this attribute, in order
    #: (e.g. ``standard``: IFRS, then RAS); others follow by value.
    prefer_attribute: Identifier | None = None
    prefer_order: list[Identifier] = Field(default_factory=list)
    purpose: str = ""

    @model_validator(mode="after")
    def one_selector(self):
        selectors = [self.subject, self.subjects, self.peers_of]
        if sum(item is not None for item in selectors) != 1:
            raise ValueError("a requirement names exactly one of subject, subjects, peers_of")
        if (self.subjects is not None or self.peers_of is not None) and not self.many:
            raise ValueError("subjects and peers_of select many items")
        return self


class FactorRequirement(Contract):
    """A factor the position is sensitive to; ``key`` selects a direct factor's instance."""

    factor_id: Identifier
    key: Identifier | None = None


class IdiosyncraticFactor(Contract):
    """A shock specific to one subject, drawn by the platform, independent of all others.

    Positions with the same subject read the same realisations, so two positions in one
    security move together.
    """

    name: Identifier
    subject: Identifier
    distribution: Literal["normal"] = "normal"
    #: Standard deviation over the calculation horizon, in ``unit``.
    sigma: NonNegative
    unit: Literal["log_return"] = "log_return"


class DataRequirements(Contract):
    data: list[DataRequirement] = Field(default_factory=list)
    factors: list[FactorRequirement] = Field(default_factory=list)


class RunOptions(Contract):
    """What a run tells a model about itself before any data is read."""

    as_of: date
    horizon: Horizon
    base_currency: Identifier = "RUB"
    #: Plugin options of the run's namespace, e.g. ``{"credit.registry_id": "..."}``.
    options: dict[str, JsonValue] = Field(default_factory=dict)


class PreparedInputs(Contract):
    """A position with the snapshot data its model asked for, resolved by the platform."""

    context: PositionContext
    model_id: Identifier
    as_of: date
    horizon: Horizon
    snapshot_id: Identifier
    data: dict[Identifier, SnapshotItem | list[SnapshotItem] | None] = Field(default_factory=dict)
    #: Unresolved requirement keys, required or not, and why (``missing``,
    #: ``dated_after_as_of``).
    missing: dict[Identifier, Identifier] = Field(default_factory=dict)
    requirements: DataRequirements = Field(default_factory=DataRequirements)
    options: dict[str, JsonValue] = Field(default_factory=dict)

    def item(self, key: str) -> SnapshotItem | None:
        value = self.data.get(key)
        if isinstance(value, list):
            raise TypeError(f"{key} resolves to several items")
        return value

    def items(self, key: str) -> list[SnapshotItem]:
        value = self.data.get(key)
        if value is None:
            return []
        return value if isinstance(value, list) else [value]


class Diagnostics(Contract):
    """What ``validate`` found about the prepared inputs.

    ``items`` with severity ``error`` stop the calculation. ``exposures`` measure the
    position on each slice's coverage basis (``None`` when it cannot be measured), so a
    position that fails still counts in the coverage it leaves uncovered. ``idiosyncratic``
    names the subject-specific shocks the platform draws before any calculation.
    """

    items: list[Diagnostic] = Field(default_factory=list)
    exposures: dict[Identifier, NonNegative | None] = Field(default_factory=dict)
    idiosyncratic: list[IdiosyncraticFactor] = Field(default_factory=list)
    data_quality: DataQuality = Field(default_factory=DataQuality)
    #: The result status of a position that does not run (``needs_review`` or ``invalid``).
    blocked_status: Literal["needs_review", "invalid"] = "needs_review"

    @property
    def blocking(self) -> list[Diagnostic]:
        return [item for item in self.items if item.severity == "error"]


class ScenarioView(Protocol):
    """The approved scenario set as a model reads it (implemented by ``msa.engine``)."""

    scenario_id: str
    macro_draws_sha256: str
    graph: TransmissionGraph | None
    parameters: dict[str, MacroParameter]
    replicates: int
    points: int

    def draws(self, name: str) -> np.ndarray:
        """Realisations of one scenario parameter, shaped ``(replicates, points)``."""

    def central(self, name: str) -> float:
        """The management central value of one scenario parameter."""

    def parameters_for(self, factor_id: str, key: str | None = None) -> list[str]:
        """Names of the parameters that move this factor (and key), sorted."""

    def idiosyncratic(self, name: str) -> np.ndarray:
        """Realisations of a subject-specific shock, shaped ``(replicates, points)``."""


@dataclass(frozen=True)
class CalculationContext:
    as_of: date
    horizon: int
    seed: int
    base_currency: str
    scenario: ScenarioView
    snapshot_id: str
    #: The run's scenario set object for the shared calculation capabilities (``msa.engine``).
    scenario_set: Any = None
    options: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None


class CalculationModel(ABC):
    """One calculation model. An instrument type may have several, chosen explicitly."""

    model_id: str
    version: str
    label: str
    instrument_types: tuple[str, ...]
    #: Metrics the model may report and those a completed result must carry.
    metrics: tuple[str, ...] = ()
    required_metrics: tuple[str, ...] = ()
    #: Portfolio slices the model contributes to.
    slices: tuple[str, ...] = ()
    #: Factors the model is sensitive to, for the catalog (``requirements`` is per position).
    factors: tuple[str, ...] = ()
    details_schema: Any = None
    description: str = ""
    limits: ApplicabilityLimits = ApplicabilityLimits()
    #: Flags of this model that send a result to review, and those that make it invalid.
    review_flags: frozenset[str] = frozenset()

    @abstractmethod
    def requirements(self, position: PositionContext, options: RunOptions) -> DataRequirements:
        """Snapshot data and factors the position needs; no data has been read yet."""

    @abstractmethod
    def validate(self, prepared: PreparedInputs) -> Diagnostics:
        """Judge the prepared inputs: missing, stale or inconsistent data, exposures."""

    @abstractmethod
    def calculate(self, prepared: PreparedInputs, context: CalculationContext) -> CalculationResult:
        """The result of the position under the approved scenario set."""

    def describe(self) -> dict:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "label": self.label,
            "instrument_types": list(self.instrument_types),
            "metrics": list(self.metrics),
            "required_metrics": list(self.required_metrics),
            "slices": list(self.slices),
            "factors": list(self.factors),
            "description": self.description,
            "limits": self.limits.model_dump(mode="json"),
        }
