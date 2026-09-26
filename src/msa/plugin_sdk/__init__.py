"""What a plugin imports: the declarations, the model interface and the data contracts.

Asset plugins declare instrument types, calculation models, metrics, factors, portfolio
slices, views, report sections and recommendation rules (``Plugin``). Agent plugins declare
nodes or subgraphs of the run's workflows (``AgentPlugin``) and whole workflows
(``WorkflowSpec``). See ``docs/plugins.md``.
"""

from msa.contracts.domain import (
    Instrument,
    Party,
    Portfolio,
    PortfolioBundle,
    Position,
    PositionContext,
)
from msa.contracts.evidence import Evidence, Parameter
from msa.contracts.result import (
    AggregationContribution,
    ArtifactRef,
    CalculationResult,
    DataQuality,
    Diagnostic,
    MetricValue,
)
from msa.contracts.risk import ApplicabilityLimits, Quantiles
from msa.contracts.snapshot import DataSnapshot, SnapshotItem
from msa.contracts.units import money, unit_price

from .mcp import CallContext, McpServerSpec, McpServices
from .model import (
    CalculationContext,
    CalculationModel,
    DataRequirement,
    DataRequirements,
    Diagnostics,
    FactorRequirement,
    IdiosyncraticFactor,
    PreparedInputs,
    RunOptions,
    ScenarioView,
)
from .plugin import DemoCase, Plugin
from .specs import (
    BASE_MONEY,
    ActionSpec,
    EditorField,
    EditorGroup,
    FactorSpec,
    InstrumentTypeSpec,
    MetricSpec,
    RecommendationRule,
    ReportSection,
    ResultView,
    SliceSpec,
    SnapshotKindSpec,
    ViewBlock,
)
from .version import SDK_VERSION, compatible

__all__ = [
    "BASE_MONEY",
    "SDK_VERSION",
    "ActionSpec",
    "AggregationContribution",
    "ApplicabilityLimits",
    "ArtifactRef",
    "CalculationContext",
    "CalculationModel",
    "CalculationResult",
    "CallContext",
    "DataQuality",
    "DataRequirement",
    "DataRequirements",
    "DataSnapshot",
    "DemoCase",
    "Diagnostic",
    "Diagnostics",
    "EditorField",
    "EditorGroup",
    "Evidence",
    "FactorRequirement",
    "FactorSpec",
    "IdiosyncraticFactor",
    "Instrument",
    "InstrumentTypeSpec",
    "McpServerSpec",
    "McpServices",
    "MetricSpec",
    "MetricValue",
    "Parameter",
    "Party",
    "Plugin",
    "Portfolio",
    "PortfolioBundle",
    "Position",
    "PositionContext",
    "PreparedInputs",
    "Quantiles",
    "RecommendationRule",
    "ReportSection",
    "ResultView",
    "RunOptions",
    "ScenarioView",
    "SliceSpec",
    "SnapshotItem",
    "SnapshotKindSpec",
    "ViewBlock",
    "compatible",
    "money",
    "unit_price",
]
