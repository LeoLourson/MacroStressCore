"""msa.contracts.domain: parties, instruments, positions, portfolios and position contexts."""

import pytest
from pydantic import ValidationError

from msa.contracts.domain import (
    Instrument,
    Party,
    Portfolio,
    PortfolioBundle,
    Position,
    PositionContext,
    contexts,
)


def party(party_id="P1", **overrides):
    values = {"party_id": party_id, "name": "Party " + party_id, "okved": "23.61"}
    values.update(overrides)
    return Party(**values)


def instrument(instrument_id="I1", issuer_id=None, **overrides):
    values = {
        "instrument_id": instrument_id,
        "instrument_type": "minimal_cash",
        "name": "Instrument " + instrument_id,
        "issuer_id": issuer_id,
    }
    values.update(overrides)
    return Instrument(**values)


def position(position_id="POS1", instrument_id="I1", **overrides):
    values = {"position_id": position_id, "instrument_id": instrument_id}
    values.update(overrides)
    return Position(**values)


def portfolio(**overrides):
    values = {"portfolio_id": "PF1", "name": "Portfolio"}
    values.update(overrides)
    return Portfolio(**values)


def bundle(*, parties=None, instruments=None, positions=None):
    return PortfolioBundle(
        portfolio=portfolio(),
        parties=parties or [],
        instruments=instruments or [],
        positions=positions or [],
    )


# -- PortfolioBundle: reference checks ------------------------------------------------


def test_bundle_accepts_consistent_references():
    b = bundle(
        parties=[party("P1")],
        instruments=[instrument("I1", issuer_id="P1")],
        positions=[position("POS1", "I1")],
    )
    assert b.instrument("I1").instrument_id == "I1"
    assert b.party("P1").party_id == "P1"


def test_bundle_party_of_none_is_none():
    assert bundle().party(None) is None


def test_bundle_rejects_duplicate_party_ids():
    with pytest.raises(ValidationError, match="duplicate party ids"):
        bundle(parties=[party("P1"), party("P1")])


def test_bundle_rejects_duplicate_instrument_ids():
    with pytest.raises(ValidationError, match="duplicate instrument ids"):
        bundle(instruments=[instrument("I1"), instrument("I1")])


def test_bundle_rejects_duplicate_position_ids():
    with pytest.raises(ValidationError, match="duplicate position ids"):
        bundle(
            instruments=[instrument("I1")],
            positions=[position("POS1", "I1"), position("POS1", "I1")],
        )


def test_bundle_rejects_instrument_with_unknown_issuer():
    with pytest.raises(ValidationError, match="unknown issuer"):
        bundle(instruments=[instrument("I1", issuer_id="NOPE")])


def test_bundle_rejects_position_with_unknown_instrument():
    with pytest.raises(ValidationError, match="unknown instrument"):
        bundle(positions=[position("POS1", "NOPE")])


def test_bundle_instrument_without_issuer_is_allowed():
    b = bundle(instruments=[instrument("I1", issuer_id=None)])
    assert b.instrument("I1").issuer_id is None


# -- PositionContext: consistency checks -----------------------------------------------


def test_position_context_accepts_matching_position_instrument_and_issuer():
    ctx = PositionContext(
        portfolio_id="PF1",
        position=position("POS1", "I1"),
        instrument=instrument("I1", issuer_id="P1"),
        issuer=party("P1"),
    )
    assert ctx.position_id == "POS1"
    assert ctx.okved == "23.61"


def test_position_context_without_issuer_has_okved_none():
    ctx = PositionContext(
        portfolio_id="PF1",
        position=position("POS1", "I1"),
        instrument=instrument("I1", issuer_id=None),
        issuer=None,
    )
    assert ctx.okved is None


def test_position_context_rejects_position_instrument_mismatch():
    with pytest.raises(ValidationError, match="do not match"):
        PositionContext(
            portfolio_id="PF1",
            position=position("POS1", "OTHER"),
            instrument=instrument("I1", issuer_id=None),
            issuer=None,
        )


def test_position_context_requires_issuer_when_instrument_names_one():
    with pytest.raises(ValidationError, match="issuer must be given exactly"):
        PositionContext(
            portfolio_id="PF1",
            position=position("POS1", "I1"),
            instrument=instrument("I1", issuer_id="P1"),
            issuer=None,
        )


def test_position_context_rejects_issuer_when_instrument_names_none():
    with pytest.raises(ValidationError, match="issuer must be given exactly"):
        PositionContext(
            portfolio_id="PF1",
            position=position("POS1", "I1"),
            instrument=instrument("I1", issuer_id=None),
            issuer=party("P1"),
        )


def test_position_context_rejects_issuer_not_matching_instrument():
    with pytest.raises(ValidationError, match="issuer does not match"):
        PositionContext(
            portfolio_id="PF1",
            position=position("POS1", "I1"),
            instrument=instrument("I1", issuer_id="P1"),
            issuer=party("OTHER"),
        )


# -- contexts(): ordering ----------------------------------------------------------------


def test_contexts_are_ordered_by_position_id():
    b = bundle(
        parties=[party("P1")],
        instruments=[instrument("I1", issuer_id="P1"), instrument("I2")],
        positions=[position("POS2", "I2"), position("POS1", "I1")],
    )
    ordered = contexts(b)
    assert [c.position_id for c in ordered] == ["POS1", "POS2"]
    assert ordered[0].issuer.party_id == "P1"
    assert ordered[1].issuer is None


def test_contexts_of_empty_bundle_is_empty():
    assert contexts(bundle()) == []
