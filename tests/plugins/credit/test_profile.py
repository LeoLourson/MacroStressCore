"""Credit plugin: schemas.terms_for, profile.requirements/build on missing statement data."""

from datetime import date

import pytest

from msa.contracts.domain import Instrument, Party, Position, PositionContext
from msa.contracts.snapshot import SnapshotItem
from msa.engine.dispatch import prepare
from msa.engine.snapshot import SnapshotIndex
from msa.platform.registry import registry
from msa.plugin_sdk.model import RunOptions
from msa.plugins.credit import profile
from msa.plugins.credit.families import family_for
from msa.plugins.credit.families.corporate import CorporateLoan
from msa.plugins.credit.schemas import terms_for

AS_OF = date(2026, 1, 1)


def amount(value, unit="fraction"):
    return {
        "value": value,
        "unit": unit,
        "evidence": [
            {"kind": "document", "source_id": "S", "locator": "l", "fragment_sha256": "a" * 64}
        ],
    }


def position_context(*, position_id="P1", issuer_okved="23.61"):
    issuer = Party(party_id="ISS1", name="Issuer", okved=issuer_okved)
    instrument = Instrument(
        instrument_id="I1",
        instrument_type="corp_loan",
        name="Loan",
        issuer_id="ISS1",
    )
    params = {
        "ead": amount(100.0, "RUB_million"),
        "lgd": amount(0.45),
        "ccf": amount(1.0),
        "import_share": amount(0.0),
    }
    position = Position(position_id=position_id, instrument_id="I1", params=params)
    return PositionContext(
        portfolio_id="PF1",
        position=position,
        instrument=instrument,
        issuer=issuer,
    )


def run_options():
    return RunOptions(
        as_of=AS_OF,
        horizon=12,
        base_currency="RUB",
        options=registry().run_options("demo"),
    )


def prepared_for(context, items=()):
    index = SnapshotIndex("SNAP1", items)
    return prepare(context, run_options(), index, registry(), sector_of=lambda s: None)


# -- schemas.terms_for --------------------------------------------------------------------


def test_terms_for_returns_the_same_schema_for_the_same_family_class():
    family = CorporateLoan()
    a = terms_for(family)
    b = terms_for(family)
    assert a is b


def test_terms_for_produces_a_valid_pydantic_model_with_covenants_and_collateral():
    schema = terms_for(CorporateLoan())
    instance = schema()
    assert instance.covenants == []
    assert instance.collateral == []


# -- profile.requirements ------------------------------------------------------------------


def test_requirements_names_statement_and_peers_and_every_credit_factor():
    ctx = position_context()
    needs = profile.requirements(ctx)
    keys = {d.key for d in needs.data}
    assert profile.STATEMENT in keys
    assert profile.PEERS in keys
    assert needs.factors  # every credit factor is a candidate sensitivity


def test_requirements_peers_selects_by_proxy_ids_when_the_analyst_chose_them():
    ctx = position_context()
    ctx = ctx.model_copy(
        update={
            "position": ctx.position.model_copy(
                update={"params": {**ctx.position.params, "proxy_peer_ids": ["PEER1", "PEER2"]}}
            )
        }
    )
    needs = profile.requirements(ctx)
    peers_req = next(d for d in needs.data if d.key == profile.PEERS)
    assert peers_req.subjects == ["PEER1", "PEER2"]
    assert peers_req.peers_of is None


# -- profile.build: missing statement and no peers -> needs_review -------------------------


def test_build_with_no_statement_and_no_peers_is_needs_review_with_reason_flag():
    ctx = position_context()
    prepared, diagnostics = prepared_for(ctx, items=())
    assert prepared is not None, diagnostics.items
    built = profile.build(prepared)
    assert built.status == "needs_review"
    assert "missing_financials_and_peers" in built.flags


def test_build_with_a_complete_statement_does_not_flag_missing_financials():
    family = family_for("corp_loan")
    statement_values = {
        "revenue": amount(1000.0, "RUB_million"),
        "cogs": amount(600.0, "RUB_million"),
        "net_debt": amount(300.0, "RUB_million"),
        "borrowing_rate": amount(0.15),
        "opex": amount(100.0, "RUB_million"),
        "opex_variable_share": amount(0.3),
        "cash": amount(50.0, "RUB_million"),
        "dso": amount(45.0, "days"),
        "dio": amount(30.0, "days"),
        "dpo": amount(30.0, "days"),
        "tax_rate": amount(0.2),
        "demand_elasticity": amount(-1.0, "ratio"),
        "pass_through": amount(0.0),
    }
    item = SnapshotItem(
        item_id="stmt1",
        kind="financial_statement",
        subject="ISS1",
        observed_on=AS_OF,
        values=statement_values,
        attributes={"standard": "IFRS"},
    )
    ctx = position_context()
    prepared, diagnostics = prepared_for(ctx, items=[item])
    assert prepared is not None, diagnostics.items
    built = profile.build(prepared)
    assert "missing_financials_and_peers" not in built.flags
    assert set(family.required).issubset(built.financials)


# -- profile.data_quality: bounds and errors ------------------------------------------------


def test_data_quality_score_within_zero_one():
    dq = profile.data_quality(1.0, 0, "IFRS")
    assert 0 <= dq <= 1


def test_data_quality_caps_at_half_for_limited_disclosure():
    dq = profile.data_quality(1.0, 0, "IFRS", limited_disclosure=True)
    assert dq <= 0.5


def test_data_quality_rejects_invalid_completeness():
    with pytest.raises(ValueError, match="Invalid data quality inputs"):
        profile.data_quality(1.5, 0, "IFRS")


def test_data_quality_rejects_unknown_standard():
    with pytest.raises(ValueError, match="Invalid data quality inputs"):
        profile.data_quality(1.0, 0, "made_up_standard")
