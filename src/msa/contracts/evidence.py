from datetime import date
from typing import Literal

from pydantic import model_validator

from .common import Contract, Identifier, Number, Sha256, Unit


class Evidence(Contract):
    kind: Literal["document", "historical_estimate", "expert_assumption"]
    source_id: Identifier
    locator: Identifier
    fragment_sha256: Sha256
    author: Identifier | None = None
    as_of: date | None = None

    @model_validator(mode="after")
    def assumption_has_owner(self):
        if self.kind == "expert_assumption" and (self.author is None or self.as_of is None):
            raise ValueError("Expert assumptions require author and as_of")
        return self


class Parameter(Contract):
    value: Number
    unit: Unit
    evidence: list[Evidence]

    @model_validator(mode="after")
    def has_source(self):
        if not self.evidence:
            raise ValueError("A parameter requires at least one source")
        return self
