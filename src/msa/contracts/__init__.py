"""Public contracts: what agents, the API and the screens exchange."""

from .api import DocumentEvent, LibraryEvent, RunRequest, TextEvent, UrlEvent, Violation
from .common import Contract, VersionStamp
from .document import Fragment, SourceDocument, Table
from .domain import Instrument, Party, Portfolio, PortfolioBundle, Position, PositionContext
from .evidence import Evidence, Parameter
from .graph import (
    Edge,
    LogNormalDistribution,
    Node,
    PointDistribution,
    TransmissionGraph,
    TriangularDistribution,
    UniformDistribution,
)
from .recommendation import Recommendation
from .report import NumberRef, Report
from .result import (
    AggregationContribution,
    CalculationResult,
    DataQuality,
    Diagnostic,
    MetricValue,
    PortfolioResult,
    SliceResult,
)
from .risk import (
    ApplicabilityLimits,
    AxisSummary,
    CovenantResult,
    Interval,
    MonthlySeries,
    Quantiles,
    ReverseStressDirection,
    ReverseStressResult,
    ShapleyContribution,
    Trajectory,
)
from .scenario import MacroParameter
from .snapshot import DataSnapshot, SnapshotItem

#: Contracts the validator dispatcher accepts by name.
CONTRACT_MODELS: dict[str, type[Contract]] = {
    model.__name__: model
    for model in (
        TransmissionGraph,
        Report,
        CalculationResult,
        Instrument,
        Position,
        PortfolioBundle,
        DataSnapshot,
    )
}

__all__ = [
    "CONTRACT_MODELS",
    "AggregationContribution",
    "ApplicabilityLimits",
    "AxisSummary",
    "CalculationResult",
    "Contract",
    "CovenantResult",
    "DataQuality",
    "DataSnapshot",
    "Diagnostic",
    "DocumentEvent",
    "Edge",
    "Evidence",
    "Fragment",
    "Instrument",
    "Interval",
    "LibraryEvent",
    "LogNormalDistribution",
    "MacroParameter",
    "MetricValue",
    "MonthlySeries",
    "Node",
    "NumberRef",
    "Parameter",
    "Party",
    "PointDistribution",
    "Portfolio",
    "PortfolioBundle",
    "PortfolioResult",
    "Position",
    "PositionContext",
    "Quantiles",
    "Recommendation",
    "Report",
    "ReverseStressDirection",
    "ReverseStressResult",
    "RunRequest",
    "ShapleyContribution",
    "SliceResult",
    "SnapshotItem",
    "SourceDocument",
    "Table",
    "TextEvent",
    "Trajectory",
    "TransmissionGraph",
    "TriangularDistribution",
    "UniformDistribution",
    "UrlEvent",
    "VersionStamp",
    "Violation",
]
