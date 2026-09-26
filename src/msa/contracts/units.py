"""Units every declaration and every number on the wire is measured in.

Plain units name a quantity: ``fraction`` (10 % is 0.1), ``days``, ``ratio`` and so on. Money
carries its currency: ``RUB_million`` is millions of roubles, ``USD_million`` millions of
dollars. A price of one unit of an instrument is ``<CCY>_per_unit`` (roubles per share).
Nothing converts silently between currencies: an exchange rate is data with its own source.
"""

import re
from typing import Annotated

from pydantic import AfterValidator

PLAIN_UNITS = frozenset(
    {
        "fraction",
        "percentage_point",
        "basis_point",
        "ratio",
        "days",
        "months",
        "years",
        "count",
        "shares",
        "price_per_100",
        "log_return",
        "dimensionless",
    }
)

#: ISO 4217 codes the platform prices in; a new currency is one more code here.
CURRENCIES = frozenset(
    {"RUB", "USD", "EUR", "CNY", "GBP", "CHF", "JPY", "HKD", "KZT", "BYN", "AED"}
)

_MONEY = re.compile(r"^([A-Z]{3})_million$")
_PRICE = re.compile(r"^([A-Z]{3})_per_unit$")


def is_unit(value: str) -> bool:
    if value in PLAIN_UNITS:
        return True
    match = _MONEY.match(value) or _PRICE.match(value)
    return bool(match) and match.group(1) in CURRENCIES


def check_unit(value: str) -> str:
    if not is_unit(value):
        raise ValueError(
            f"unknown unit {value!r}: use one of {sorted(PLAIN_UNITS)}, "
            "<CCY>_million for money or <CCY>_per_unit for a unit price"
        )
    return value


def check_currency(value: str) -> str:
    if value not in CURRENCIES:
        raise ValueError(f"unknown currency {value!r}; known: {', '.join(sorted(CURRENCIES))}")
    return value


def money(currency: str) -> str:
    """Millions of ``currency``: the unit money amounts are reported in."""
    return f"{check_currency(currency)}_million"


def unit_price(currency: str) -> str:
    return f"{check_currency(currency)}_per_unit"


def currency_of(unit: str) -> str | None:
    """The currency a money or price unit is measured in; ``None`` for plain units."""
    match = _MONEY.match(unit) or _PRICE.match(unit)
    return match.group(1) if match else None


def is_money(unit: str) -> bool:
    return bool(_MONEY.match(unit))


Unit = Annotated[str, AfterValidator(check_unit)]
Currency = Annotated[str, AfterValidator(check_currency)]
