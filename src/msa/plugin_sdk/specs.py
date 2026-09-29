"""Declarations a plugin makes about what it adds: types, metrics, factors, slices, views.

Every identifier a plugin declares — metric, factor, slice, model, rule — lives in the
plugin's namespace (``credit.icr``, ``equity.pnl``), so two plugins may use the same short
name without conflict. Labels are Russian: the screens, the report and the MCP tools show
them as declared here and nowhere else.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

#: Money in the portfolio's base currency, resolved per run to ``<BASE>_million``.
BASE_MONEY = "base_money"
#: Editor-only units resolved from the position and portfolio currencies by the UI.
#: Stored snapshot values still use concrete units such as RUB_per_unit and ratio.
EDITOR_UNIT_ALIASES = frozenset({BASE_MONEY, "instrument_price", "fx_quote"})

MetricKind = Literal["distribution", "value"]
Period = Literal["as_of", "horizon_end", "horizon", "monthly_path"]
Direction = Literal["higher_is_worse", "lower_is_worse", "neutral"]
Aggregation = Literal["sum_by_realisation", "none"]
FactorScope = Literal["graph", "global", "sector", "instrument", "currency_pair"]
FactorApplication = Literal["relative", "additive", "log"]
FactorQuantity = Literal["relative_change", "days", "rate_annual", "log_return"]
Temporal = Literal["monthly_path", "horizon"]
FieldKind = Literal["number", "text", "date", "dates", "enum", "boolean", "table"]


@dataclass(frozen=True)
class MetricSpec:
    """One metric: what it means, in what unit, for which period, and how it adds up."""

    metric_id: str
    label: str
    #: A unit of ``msa.contracts.units`` or ``BASE_MONEY``.
    unit: str
    kind: MetricKind = "distribution"
    period: Period = "horizon_end"
    direction: Direction = "neutral"
    #: ``sum_by_realisation``: positions add up inside each realisation (a slice measure).
    aggregation: Aggregation = "none"
    description: str = ""
    decimals: int = 2


@dataclass(frozen=True)
class SliceSpec:
    """A portfolio slice: one measure with one economic meaning, summed by realisation."""

    slice_id: str
    label: str
    #: What the slice's losses are, as a phrase: «Рост ожидаемых потерь».
    measure_label: str
    #: The coverage basis: ``ead`` or ``market_value``.
    exposure_basis: str
    exposure_label: str
    unit: str = BASE_MONEY
    #: Uncovered exposure above this share makes the slice ``incomplete``.
    coverage_limit: float = 0.05
    description: str = ""


@dataclass(frozen=True)
class FactorSpec:
    """A risk factor a scenario may move, and how a shock of it is applied."""

    factor_id: str
    label: str
    #: Unit of the scenario values: ``fraction`` (relative), ``days``, ``log_return``.
    unit: Literal["fraction", "days", "log_return"]
    scope: FactorScope
    application: FactorApplication
    quantity: FactorQuantity
    temporal: Temporal = "horizon"
    #: What the key of a direct factor names: «Индекс рынка», «Валютная пара».
    key_label: str = ""
    description: str = ""
    #: Values at or below this bound are outside the factor's domain (-1 for relative).
    lower_bound: float | None = None


@dataclass(frozen=True)
class EditorField:
    """One input of the portfolio editor and where the typed value goes."""

    name: str
    label: str
    #: ``terms``, ``position`` or ``snapshot:<kind>``: the part of the data it is stored in.
    target: str
    #: A concrete unit, or one of EDITOR_UNIT_ALIASES for a currency-dependent label.
    unit: str | None = None
    kind: FieldKind = "number"
    required: bool = False
    default: Any = None
    #: Flag raised when the default stands in for missing data.
    assumption: str | None = None
    hint: str = ""
    advanced: bool = False
    minimum: float | None = None
    maximum: float | None = None
    options: tuple[tuple[str, str], ...] = ()
    #: Columns of a ``table`` field.
    columns: tuple["EditorField", ...] = ()
    #: Optional draft-row attribute and longest-prefix defaults, owned by the plugin.
    derive_from: str | None = None
    derived_values: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class EditorGroup:
    group_id: str
    title: str
    fields: tuple[EditorField, ...]
    folded: bool = False


@dataclass(frozen=True)
class InstrumentTypeSpec:
    """An instrument type: the schemas of its terms and positions, its models and editor."""

    type_id: str
    label: str
    #: Pydantic models ``Instrument.terms`` and ``Position.params`` are validated against.
    terms_schema: type[BaseModel]
    position_schema: type[BaseModel]
    default_model: str
    schema_version: str = "1"
    description: str = ""
    #: Whether an issuer is required; a sector-reached event needs one.
    issuer_required: bool = True
    #: The editor value that names the security (a share's ticker): rows of this type and
    #: currency with the same value are positions in one instrument of one issuer.
    identity: str | None = None
    editor: tuple[EditorGroup, ...] = ()
    #: Turns an editor row into instrument terms, position params and snapshot items.
    from_draft: Callable[..., Any] | None = None


@dataclass(frozen=True)
class SnapshotKindSpec:
    """A kind of snapshot item a plugin reads, for the catalog and the import check."""

    kind: str
    label: str
    subject: str
    #: value name -> its unit in words; a price is in the instrument's own currency.
    values: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ViewBlock:
    """A standard block of a result view: a metric, a series, a table or the sources."""

    kind: Literal["metric", "metrics", "series", "table", "sources", "histogram", "text"]
    title: str = ""
    #: Metrics the block shows; a histogram marks the P5, P50 and P95 of its metric.
    metric_ids: tuple[str, ...] = ()
    #: JSON Pointer into ``CalculationResult.details``.
    path: str = ""
    columns: tuple[tuple[str, str], ...] = ()
    hint: str = ""


@dataclass(frozen=True)
class ResultView:
    """How a result is shown. A UI plugin may render its own component; the blocks remain
    the standard view the screens fall back to when that component is not installed."""

    view_id: str
    instrument_types: tuple[str, ...]
    component: str | None = None
    blocks: tuple[ViewBlock, ...] = ()
    #: Metrics of the positions table on the run page, in order.
    summary_metrics: tuple[str, ...] = ()
    #: Russian names of what ``details`` carries (series, covenant metrics), by key.
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionSpec:
    action_id: str
    label: str


@dataclass(frozen=True)
class RecommendationRule:
    """A rule of the table that chooses actions (TZ 3.6): the observation it reads, its
    default threshold and the actions it recommends. Thresholds in force are data."""

    rule_id: str
    label: str
    observation: str
    operator: Literal["lt", "le", "gt", "ge"]
    threshold: float
    actions: tuple[str, ...]
    unit: str = ""
    #: Fires only when no other rule of the plugin fired for the position.
    fallback_only: bool = False
    #: Whether the report states the observed value next to the recommendation.
    cite_value: bool = False


@dataclass(frozen=True)
class ReportSection:
    """A section of the report text. ``render`` writes lines through ``ReportContext``, whose
    ``cite`` ties every number to the metric tree; nothing else may write a number."""

    section_id: str
    title: str
    order: int
    render: Callable[[Any], list[str]]
    #: Instrument types whose results the section reads; empty — any.
    instrument_types: tuple[str, ...] = ()
