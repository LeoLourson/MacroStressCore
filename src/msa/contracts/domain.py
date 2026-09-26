"""Portfolio holdings: parties, instruments, positions and portfolios.

The general contract knows no financial field of any asset family. ``Instrument.terms`` and
``Position.params`` are plugin data: each instrument type validates them against its own
versioned schema (``msa.plugin_sdk.InstrumentTypeSpec``), so a new family needs no change
here and no migration of the database.
"""

from datetime import date
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from .common import Contract, Identifier
from .evidence import Evidence
from .units import Currency

PartyKind = Literal["company", "project", "bank", "sovereign", "fund", "individual", "other"]


class Party(Contract):
    """An issuer, borrower or counterparty. An instrument may have none (cash, a commodity)."""

    party_id: Identifier
    name: Identifier
    kind: PartyKind = "company"
    #: OKVED 2 code of the party's activity: the sector the economic graph reaches.
    okved: Identifier | None = None
    country: Identifier | None = None
    description: str = ""
    evidence: list[Evidence] = Field(default_factory=list)


class Instrument(Contract):
    """The economic terms of one instrument; typed terms belong to its type's plugin."""

    instrument_id: Identifier
    #: A type registered by a plugin (``msa.platform.registry``).
    instrument_type: Identifier
    name: Identifier
    #: The currency the instrument is denominated and priced in.
    currency: Currency = "RUB"
    issuer_id: Identifier | None = None
    terms: dict[str, JsonValue] = Field(default_factory=dict)
    #: Version of the plugin schema ``terms`` were written against.
    schema_version: Identifier = "1"


class Position(Contract):
    """Holding one instrument in a portfolio: quantity and position parameters."""

    position_id: Identifier
    instrument_id: Identifier
    params: dict[str, JsonValue] = Field(default_factory=dict)
    schema_version: Identifier = "1"
    #: An explicitly chosen calculation model; unset, the instrument type's default model.
    model_id: Identifier | None = None


class Portfolio(Contract):
    portfolio_id: Identifier
    name: Identifier
    #: Every result of the portfolio is reported in this currency.
    base_currency: Currency = "RUB"
    #: The date the portfolio's figures are valued at, when it declares one.
    as_of: date | None = None
    #: The data snapshot runs of this portfolio read unless a run names another.
    snapshot_id: Identifier | None = None
    builtin: bool = False
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class PortfolioBundle(Contract):
    """A portfolio with everything its positions refer to: the import and export format."""

    portfolio: Portfolio
    parties: list[Party] = Field(default_factory=list)
    instruments: list[Instrument] = Field(default_factory=list)
    positions: list[Position] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_resolve(self):
        parties = [item.party_id for item in self.parties]
        instruments = [item.instrument_id for item in self.instruments]
        positions = [item.position_id for item in self.positions]
        for name, ids in (("party", parties), ("instrument", instruments), ("position", positions)):
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {name} ids")
        for instrument in self.instruments:
            if instrument.issuer_id is not None and instrument.issuer_id not in parties:
                raise ValueError(
                    f"instrument {instrument.instrument_id} names unknown issuer "
                    f"{instrument.issuer_id}"
                )
        for position in self.positions:
            if position.instrument_id not in instruments:
                raise ValueError(
                    f"position {position.position_id} holds unknown instrument "
                    f"{position.instrument_id}"
                )
        return self

    def instrument(self, instrument_id: str) -> Instrument:
        return next(item for item in self.instruments if item.instrument_id == instrument_id)

    def party(self, party_id: str | None) -> Party | None:
        if party_id is None:
            return None
        return next((item for item in self.parties if item.party_id == party_id), None)


class PositionContext(Contract):
    """One position with its instrument and issuer: the unit a run selects and calculates."""

    portfolio_id: Identifier
    base_currency: Currency = "RUB"
    position: Position
    instrument: Instrument
    issuer: Party | None = None

    @model_validator(mode="after")
    def consistent(self):
        if self.position.instrument_id != self.instrument.instrument_id:
            raise ValueError("position and instrument do not match")
        if (self.issuer is None) != (self.instrument.issuer_id is None):
            raise ValueError("the issuer must be given exactly when the instrument names one")
        if self.issuer is not None and self.issuer.party_id != self.instrument.issuer_id:
            raise ValueError("issuer does not match the instrument")
        return self

    @property
    def position_id(self) -> str:
        return self.position.position_id

    @property
    def okved(self) -> str | None:
        return self.issuer.okved if self.issuer else None


def contexts(bundle: PortfolioBundle) -> list[PositionContext]:
    """Every position of the bundle with what it refers to, ordered by position id."""
    return [
        PositionContext(
            portfolio_id=bundle.portfolio.portfolio_id,
            base_currency=bundle.portfolio.base_currency,
            position=position,
            instrument=bundle.instrument(position.instrument_id),
            issuer=bundle.party(bundle.instrument(position.instrument_id).issuer_id),
        )
        for position in sorted(bundle.positions, key=lambda item: item.position_id)
    ]
