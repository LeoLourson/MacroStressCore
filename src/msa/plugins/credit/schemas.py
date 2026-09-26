"""Versioned schemas of the credit types: instrument terms and position parameters.

Numbers are ``Parameter`` values: each carries its unit and its sources, so no figure of a
credit position lacks provenance. EAD, LGD, CCF, covenants and collateral belong here, not
to the platform's general instrument.
"""

from pydantic import Field, create_model, model_validator

from msa.contracts.common import Contract, Identifier, Number
from msa.contracts.evidence import Parameter

from .contracts import Collateral, Covenant
from .family import CreditFamily

SCHEMA_VERSION = "1"

#: Snapshot kinds the credit plugin declares: the borrower's statement and a rate curve.
FINANCIAL_STATEMENT = "financial_statement"
RATE = "rate"


class CreditPosition(Contract):
    """The bank's exposure to the borrower: what is at risk and what is recovered."""

    ead: Parameter
    lgd: Parameter
    ccf: Parameter
    import_share: Parameter
    #: Factor node id -> the borrower's own elasticity to it, when it differs from the graph.
    driver_elasticity: dict[Identifier, Number] = Field(default_factory=dict)
    #: Issuers whose statements stand in for missing data, when the analyst chose them.
    proxy_peer_ids: list[Identifier] = Field(default_factory=list)
    #: The data provider's own verdict: ``needs_review`` holds the position out of the run.
    status: str = Field(default="ok", pattern=r"^(ok|needs_review)$")
    flags: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def units(self):
        if self.ead.unit != "RUB_million":
            raise ValueError("ead is measured in RUB_million")
        if self.ead.value <= 0:
            raise ValueError("ead must be positive")
        for name in ("lgd", "ccf", "import_share"):
            parameter = getattr(self, name)
            if parameter.unit != "fraction" or not 0 <= parameter.value <= 1:
                raise ValueError(f"{name} is a fraction within [0, 1]")
        if self.status == "needs_review" and not self.flags:
            raise ValueError("needs_review requires a reason in flags")
        return self


def terms_schema(family: CreditFamily):
    """Covenants, collateral and the family's contractual terms, each a sourced number."""
    fields = {
        "covenants": (list[Covenant], Field(default_factory=list)),
        "collateral": (list[Collateral], Field(default_factory=list)),
    }
    for item in family.fields_from("terms"):
        fields[item.name] = (Parameter | None, None)
    name = type(family).__name__ + "Terms"
    return create_model(name, __base__=Contract, **fields)


TERMS_SCHEMAS = {}


def terms_for(family: CreditFamily):
    key = type(family).__name__
    if key not in TERMS_SCHEMAS:
        TERMS_SCHEMAS[key] = terms_schema(family)
    return TERMS_SCHEMAS[key]
