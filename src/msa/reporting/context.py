"""What a report section writes with: citations, names, flags, intervals.

A section never formats a number itself. ``cite`` reads the value from the metric tree,
records the citation (``NumberRef``) and returns the rounded text, so V9 can resolve every
number of the report against the same tree the screens read.
"""

from dataclasses import dataclass, field

from msa.contracts.report import NumberRef
from msa.contracts.result import CalculationResult

from . import wording
from .numbers import extract_numbers, pointer_token, resolve_pointer, rounded


def display_id(value: str) -> str:
    starts_with_number = value[:1].isdigit() or (value[:1] in {"+", "-"} and value[1:2].isdigit())
    return f"#{value}" if starts_with_number else value


def plain(text) -> bool:
    # A name with digits would read as an untraceable number (V9); the identifier stands in.
    return bool(text) and not extract_numbers(text)


def sentence(text: str) -> str:
    """End a sentence once: «млн руб.» already carries its period."""
    return text if text.endswith(".") else text + "."


def join(items) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " и " + items[-1]


@dataclass
class ReportContext:
    tree: dict
    results: list[CalculationResult]
    portfolio: object
    registry: object
    names: dict[str, str] = field(default_factory=dict)
    #: Graph node id -> label, for channels.
    channels: dict[str, str] = field(default_factory=dict)
    #: Scenario parameter name -> the analyst's label.
    shock_labels: dict[str, str] = field(default_factory=dict)
    #: Channel -> factor id of the scenario parameters on it.
    channel_factors: dict[str, str] = field(default_factory=dict)
    #: Plugin id -> what its run options say (the credit calibration in force, ...).
    notes: dict[str, dict] = field(default_factory=dict)
    numbers: list[NumberRef] = field(default_factory=list)

    # Numbers ---------------------------------------------------------------------------

    def value(self, path: str):
        return resolve_pointer(self.tree, path)

    def cite(self, path: str, places: int = 2) -> str:
        """The rounded value at ``path``, with a decimal comma, recorded for V9."""
        value = self.value(path)
        self.numbers.append(NumberRef(value=value, metric_path=path, rounding=places))
        return f"{rounded(value, places):.{places}f}".replace(".", ",")

    def interval(self, path: str, unit: str, places: int = 2) -> str:
        """P50 with P5–P95 of the node at ``path``: the interval is the result."""
        low, high = f"{path}/p05", f"{path}/p95"
        if rounded(self.value(low), places) == rounded(self.value(high), places):
            return f"{self.cite(path + '/p50', places)} {unit} во всех сценариях"
        return (
            f"{self.cite(path + '/p50', places)} {unit} по медиане (P50), P5–P95 — от "
            f"{self.cite(low, places)} до {self.cite(high, places)} {unit}"
        )

    # Paths and names -------------------------------------------------------------------

    @staticmethod
    def base(position_id: str) -> str:
        return "/positions/" + pointer_token(position_id)

    def metric_path(self, position_id: str, metric_id: str) -> str:
        return f"{self.base(position_id)}/metrics/{pointer_token(metric_id)}"

    def position(self, position_id: str) -> str:
        name = self.names.get(position_id)
        return f"{name} ({display_id(position_id)})" if plain(name) else display_id(position_id)

    def channel(self, channel_id: str) -> str:
        name = self.channels.get(channel_id)
        return f"«{name}»" if plain(name) else display_id(channel_id)

    def flag(self, code: str) -> str:
        return wording.flag(code, self.registry.flag_wording(), self.shock_labels)

    def status(self, status: str) -> str:
        return wording.STATUSES.get(status, status)

    def of_types(self, types) -> list[CalculationResult]:
        types = set(types)
        return [r for r in self.results if not types or r.instrument_type in types]

    def label(self, metric_id: str) -> str:
        spec = self.registry.metrics.get(metric_id)
        return spec.label if spec else metric_id
