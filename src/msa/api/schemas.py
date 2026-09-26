"""Request bodies that are not public contracts: they belong to one HTTP operation each."""

from typing import Annotated

from pydantic import Field, HttpUrl, JsonValue, model_validator

from msa.agents.causal_output import ScenarioParameter
from msa.contracts import TransmissionGraph
from msa.contracts.common import Contract, Identifier


class IngestRequest(Contract):
    text: Identifier | None = None
    url: HttpUrl | None = None
    content_base64: str | None = Field(default=None, max_length=28 * 1024 * 1024)
    filename: str = "document.pdf"

    @model_validator(mode="after")
    def one(self):
        if sum(x is not None for x in (self.text, self.url, self.content_base64)) != 1:
            raise ValueError("Specify exactly one of text, url or content_base64")
        return self


class ExplainRequest(Contract):
    """A question about a calculated run."""

    question: Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]


# Why the risk manager returned or rejected the report, in their own words.
Reason = Annotated[str, Field(min_length=1, max_length=4000, pattern=r"\S")]


class ResumeRequest(Contract):
    graph: TransmissionGraph | None = None
    approved: bool | None = Field(default=None, strict=True)
    # A negative decision either returns the report to the analyst or closes the run.
    returned: bool = Field(default=False, strict=True)
    reason: Reason | None = None
    # Sent with the graph; omitted, the proposed scenario is confirmed unchanged.
    macro_parameters: dict[Identifier, ScenarioParameter] | None = None

    @model_validator(mode="after")
    def one(self):
        if (self.graph is None) == (self.approved is None):
            raise ValueError("Specify graph or approved")
        if self.macro_parameters is not None and self.graph is None:
            raise ValueError("macro_parameters are confirmed together with the graph")
        if self.approved is False and self.reason is None:
            raise ValueError("Returning or rejecting a report requires a reason")
        if self.returned and self.approved is not False:
            raise ValueError("returned belongs to a negative decision")
        return self


class ScenarioCheckRequest(Contract):
    """An analyst's draft at the graph stop, checked before it is sent with resume."""

    # A draft may be invalid, so it is taken as data and judged by the validators.
    graph: dict[str, JsonValue]
    macro_parameters: dict[Identifier, dict[str, JsonValue]] = Field(default_factory=dict)
    required: bool = False
    run_id: Identifier | None = None
