"""msa.contracts.units: the unit vocabulary every declaration is measured in."""

import pytest
from pydantic import BaseModel, ValidationError

from msa.contracts.units import (
    Currency,
    Unit,
    check_currency,
    check_unit,
    currency_of,
    is_money,
    is_unit,
    money,
    unit_price,
)


@pytest.mark.parametrize(
    "unit",
    [
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
    ],
)
def test_plain_units_are_recognised(unit):
    assert is_unit(unit)
    assert check_unit(unit) == unit


@pytest.mark.parametrize(
    "currency", ["RUB", "USD", "EUR", "CNY", "GBP", "CHF", "JPY", "HKD", "KZT", "BYN", "AED"]
)
def test_money_and_price_units_for_every_currency(currency):
    assert is_unit(f"{currency}_million")
    assert is_unit(f"{currency}_per_unit")
    assert money(currency) == f"{currency}_million"
    assert unit_price(currency) == f"{currency}_per_unit"


def test_unknown_unit_is_rejected():
    assert not is_unit("kilograms")
    with pytest.raises(ValueError, match="unknown unit"):
        check_unit("kilograms")


def test_money_unit_of_unknown_currency_is_rejected():
    assert not is_unit("XXX_million")
    assert not is_unit("XXX_per_unit")


def test_check_currency_rejects_unknown_code():
    with pytest.raises(ValueError, match="unknown currency"):
        check_currency("XXX")


def test_money_and_unit_price_reject_unknown_currency():
    with pytest.raises(ValueError, match="unknown currency"):
        money("XXX")
    with pytest.raises(ValueError, match="unknown currency"):
        unit_price("XXX")


def test_currency_of_money_and_price_units():
    assert currency_of("RUB_million") == "RUB"
    assert currency_of("USD_per_unit") == "USD"


def test_currency_of_plain_unit_is_none():
    assert currency_of("fraction") is None
    assert currency_of("dimensionless") is None


def test_currency_of_does_not_check_registered_currencies():
    # currency_of is a pure shape match; it does not consult CURRENCIES.
    assert currency_of("XXX_million") == "XXX"


def test_is_money_true_only_for_million_unit():
    assert is_money("RUB_million")
    assert not is_money("RUB_per_unit")
    assert not is_money("fraction")


def test_unit_and_currency_annotated_types_validate_in_a_model():
    class M(BaseModel):
        unit: Unit
        currency: Currency

    m = M(unit="days", currency="USD")
    assert m.unit == "days"
    assert m.currency == "USD"

    with pytest.raises(ValidationError):
        M(unit="not_a_unit", currency="USD")
    with pytest.raises(ValidationError):
        M(unit="days", currency="ZZZ")
