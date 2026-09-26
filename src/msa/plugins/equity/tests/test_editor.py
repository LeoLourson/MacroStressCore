"""Equity plugin: editor.from_draft() turns a typed row into terms, params and snapshot items."""

from datetime import date

import pytest

from msa.api.portfolio_draft import DraftContext
from msa.plugins.equity.editor import from_draft

CTX = DraftContext(
    author="analyst",
    today=date(2026, 9, 11),
    source_id="draft:test",
    portfolio_id="PF1",
    base_currency="RUB",
)


def row(**values):
    base = {
        "position_id": "P1",
        "currency": "RUB",
        "values": {
            "quantity": 100.0,
            "ticker": "OIL",
            "market_index": "MOEX",
            "sector": "oil_gas",
            "price": 250.0,
            "beta_market": 1.1,
            "beta_sector": 0.9,
            "residual_volatility": 0.2,
            "dividend": 5.0,
        },
    }
    base.update(values)
    return base


def test_from_draft_produces_terms_params_and_three_items_for_a_base_currency_share():
    result = from_draft(row(), CTX)
    assert result["terms"] == {"ticker": "OIL", "market_index": "MOEX", "sector": "oil_gas"}
    assert result["params"]["quantity"]["value"] == 100.0
    assert result["params"]["direction"] == "long"
    kinds = [item["kind"] for item in result["items"]]
    assert kinds == ["price", "sensitivity", "dividend"]


def test_from_draft_evidence_is_an_expert_assumption_by_the_author():
    result = from_draft(row(), CTX)
    evidence = result["params"]["quantity"]["evidence"][0]
    assert evidence["kind"] == "expert_assumption"
    assert evidence["author"] == "analyst"
    assert evidence["as_of"] == "2026-09-11"


def test_from_draft_rejects_unknown_field():
    with pytest.raises(ValueError, match="unknown fields"):
        from_draft(row(values={**row()["values"], "mystery": 1}), CTX)


def test_from_draft_rejects_missing_required_field():
    values = row()["values"].copy()
    del values["beta_market"]
    with pytest.raises(ValueError, match="required fields"):
        from_draft(row(values=values), CTX)


def test_from_draft_foreign_currency_without_fx_rate_is_rejected():
    with pytest.raises(ValueError, match="the rate of USD to RUB"):
        from_draft(row(currency="USD"), CTX)


def test_from_draft_foreign_currency_with_fx_rate_adds_an_fx_item():
    values = {**row()["values"], "fx_rate": 92.5}
    result = from_draft(row(currency="USD", values=values), CTX)
    kinds = [item["kind"] for item in result["items"]]
    assert kinds == ["price", "sensitivity", "dividend", "fx_rate"]
    fx_item = result["items"][-1]
    assert fx_item["subject"] == "USD/RUB"
    assert fx_item["values"]["rate"]["value"] == 92.5


def test_from_draft_price_and_dividend_units_use_the_position_currency():
    result = from_draft(row(), CTX)
    price_item = next(i for i in result["items"] if i["kind"] == "price")
    assert price_item["values"]["price"]["unit"] == "RUB_per_unit"


@pytest.mark.parametrize(
    "okved,sector",
    [
        ("46.63", "industrials"),
        ("06.10", "oil_gas"),
        ("62.01", "technology"),
        ("46.71", "oil_gas"),
        ("46.11", "trade"),
        ("19.20", "oil_gas"),
    ],
)
def test_sector_is_derived_and_sensitivity_uses_the_same_key(okved, sector):
    values = row()["values"].copy()
    del values["sector"]
    del values["market_index"]
    result = from_draft(row(values=values, okved=okved), CTX)
    assert result["terms"]["sector"] == sector
    assert result["terms"]["market_index"] == "MOEX"
    sensitivity = next(item for item in result["items"] if item["kind"] == "sensitivity")
    assert sensitivity["attributes"]["sector"] == sector
    assert "sector" not in values  # Do not mutate the submitted draft.


def test_explicit_calibration_sector_wins_over_okved_default():
    result = from_draft(row(okved="62.01"), CTX)
    assert result["terms"]["sector"] == "oil_gas"


def test_unmapped_okved_requires_an_explicit_sector():
    values = row()["values"].copy()
    del values["sector"]
    with pytest.raises(ValueError, match="sector"):
        from_draft(row(values=values, okved="99"), CTX)
