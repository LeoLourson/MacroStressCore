"""msa.api.portfolio_draft.build: identity merges lots of one security (D10); editor bounds
enforced server-side (I3).
"""

from datetime import date

import pytest

from msa.api.portfolio_draft import DraftPosition, PortfolioDraft, build
from msa.platform.registry import registry

AS_OF = date(2026, 9, 11)
REGISTRY = registry()


def row(position_id, **overrides):
    base = {
        "position_id": position_id,
        "name": "Эмитент",
        "instrument_type": "common_stock",
        "okved": "46.63",
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
    base.update(overrides)
    return base


def build_rows(*rows):
    draft = PortfolioDraft(
        name="Портфель", positions=[DraftPosition.model_validate(r) for r in rows]
    )
    return build(draft, author="analyst", today=AS_OF, registry=REGISTRY, portfolio_id="PF1")


# -- D10: rows of the same type, currency and identity merge into one instrument ------------


def test_two_rows_of_the_same_ticker_become_one_instrument_and_issuer_with_two_positions():
    bundle, _ = build_rows(row("P1"), row("P2"))
    assert len(bundle.instruments) == 1
    assert len(bundle.parties) == 1
    assert {p.position_id for p in bundle.positions} == {"P1", "P2"}
    assert {p.instrument_id for p in bundle.positions} == {bundle.instruments[0].instrument_id}


def test_rows_of_the_same_ticker_with_different_data_raise_naming_the_ticker():
    other_price = row("P2", values={**row("P2")["values"], "price": 300.0})
    with pytest.raises(ValueError, match="OIL"):
        build_rows(row("P1"), other_price)


def test_rows_of_different_tickers_stay_separate_instruments_and_issuers():
    other_ticker = row("P2", values={**row("P2")["values"], "ticker": "GAS"})
    bundle, _ = build_rows(row("P1"), other_ticker)
    assert len(bundle.instruments) == 2
    assert len(bundle.parties) == 2


# -- I3: the editor's declared bounds are enforced on the server too ------------------------


def test_a_field_above_its_declared_maximum_is_rejected_naming_the_field():
    over = row("P1", values={**row("P1")["values"], "residual_volatility": 20})
    with pytest.raises(ValueError, match="residual_volatility"):
        build_rows(over)
