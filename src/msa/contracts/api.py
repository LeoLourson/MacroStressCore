"""Request contracts of the HTTP API."""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, HttpUrl

from .common import Contract, Identifier, McPoints, Seed


class TextEvent(Contract):
    kind: Literal["text"]
    text: Identifier


class UrlEvent(Contract):
    kind: Literal["url"]
    url: HttpUrl


class DocumentEvent(Contract):
    kind: Literal["doc_id"]
    doc_id: Identifier


class LibraryEvent(Contract):
    """An event of the demo library, by its id; demo namespace only."""

    kind: Literal["library"]
    id: Identifier


Event = Annotated[TextEvent | UrlEvent | DocumentEvent | LibraryEvent, Field(discriminator="kind")]

# How strong the event may be, in the words of the person starting the run.
ScenarioWords = Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]


class RunRequest(Contract):
    """A run is fixed to its workflow, positions, models, data snapshot and scenario."""

    portfolio_id: Identifier
    event: Event
    #: The process to run (``GET /v1/workflows``).
    workflow_id: Identifier = "stress_test"
    #: The valuation date; unset, the portfolio's own valuation date applies.
    as_of: date | None = None
    #: The data snapshot the run reads; unset, the portfolio's own snapshot.
    snapshot_id: Identifier | None = None
    seed: Seed = 20260911
    mc_points: McPoints = 8192
    scenario: ScenarioWords | None = None
    position_ids: list[Identifier] | None = None
    #: An explicitly chosen model by position id or instrument type (``GET /v1/models``).
    models: dict[Identifier, Identifier] = Field(default_factory=dict)
    #: Agent plugins off by default that join this run (``GET /v1/workflows``).
    agents: list[Identifier] = Field(default_factory=list)
    #: Stop at the graph even when the causal agent's answer passes every check.
    request_graph_review: bool = Field(default=False, strict=True)
    #: Demo namespace only: automatic approval for rehearsals.
    auto_approve: bool = Field(default=False, strict=True)


class Violation(Contract):
    rule_id: Annotated[str, Field(pattern=r"^(V(?:[1-9]|1[01])|SCENARIO)$")]
    path: str  # RFC 6901 JSON Pointer; empty string denotes the entire payload.
    message: Identifier
