"""Schemas of an ordinary share: the instrument's terms, the position and the result."""

from typing import Literal

from pydantic import Field, model_validator

from msa.contracts.common import Contract, Identifier, NonNegative, Number, Positive
from msa.contracts.evidence import Parameter

SCHEMA_VERSION = "1"

#: Snapshot kinds the equity plugin declares.
SENSITIVITY = "sensitivity"
#: Annual residual volatility above 200 % is a typing error (20 for 0.2), not a view.
MAX_RESIDUAL_VOLATILITY = 2.0
DIVIDEND = "dividend"


class ShareTerms(Contract):
    """What identifies the share and which market and sector factors move it."""

    ticker: Identifier
    exchange: Identifier | None = None
    #: The market index whose factor (``equity.market``) the share is sensitive to.
    market_index: Identifier
    #: The sector factor (``equity.sector``) key the share is sensitive to.
    sector: Identifier


class SharePosition(Contract):
    """A long position: the number of shares held. Short positions are not modelled yet."""

    quantity: Parameter
    direction: Literal["long"] = "long"

    @model_validator(mode="after")
    def shares(self):
        if self.quantity.unit != "shares" or self.quantity.value <= 0:
            raise ValueError("quantity is a positive number of shares")
        return self


class FactorContribution(Contract):
    factor_id: Identifier
    key: Identifier | None = None
    label: str
    #: Shapley contribution to the central P&L, in the base currency's millions.
    contribution: Number


class Histogram(Contract):
    edges: list[Number] = Field(min_length=2)
    counts: list[int]

    @model_validator(mode="after")
    def sized(self):
        if len(self.counts) != len(self.edges) - 1:
            raise ValueError("a histogram has one count fewer than edges")
        return self


class Central(Contract):
    log_return: Number
    price: Positive
    fx: Positive
    value: NonNegative
    dividends: NonNegative
    pnl: Number
    pnl_vs_base: Number


class ShareDetails(Contract):
    """The equity model's own result: inputs as read, the central scenario and the tails."""

    currency: Identifier
    base_currency: Identifier
    price: Positive
    price_date: str
    fx: Positive
    quantity: Positive
    beta_market: Number
    beta_sector: Number
    residual_sigma: NonNegative
    dividend_per_share: NonNegative
    value_current: NonNegative
    central: Central
    factor_contributions: list[FactorContribution]
    loss_histogram: Histogram
    conventions: list[str] = Field(default_factory=list)
