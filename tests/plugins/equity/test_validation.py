"""Equity plugin: ShareFactorStress.requirements() and validate() diagnostic codes.

Builds on the plugin's own demo case (a RUB share and a USD share), read directly rather
than run end to end, so each broken snapshot item can be tested in isolation.
"""

from datetime import timedelta

from msa.contracts.domain import contexts
from msa.contracts.snapshot import DataSnapshot
from msa.engine.dispatch import prepare
from msa.engine.snapshot import SnapshotIndex
from msa.platform.registry import registry
from msa.plugin_sdk.model import RunOptions
from msa.plugins.equity.demo import cases
from msa.plugins.equity.model import ShareFactorStress

CASE = cases()[0]
AS_OF = CASE.bundle.portfolio.as_of


def context_of(position_id):
    return next(c for c in contexts(CASE.bundle) if c.position_id == position_id)


def options():
    return RunOptions(as_of=AS_OF, horizon=12, base_currency=CASE.bundle.portfolio.base_currency)


def prepared_and_diagnostics(position_id, snapshot=None):
    snap = snapshot or CASE.snapshot
    index = SnapshotIndex(snap.snapshot_id, snap.items)
    sectors = {p.party_id: p.okved for p in CASE.bundle.parties}
    return prepare(context_of(position_id), options(), index, registry(), sector_of=sectors.get)


def edit_item(snapshot, item_id, **changes):
    raw = snapshot.model_dump(mode="json")
    for item in raw["items"]:
        if item["item_id"] == item_id:
            item.update(changes)
    return DataSnapshot.model_validate(raw)


def edit_values(snapshot, item_id, **value_changes):
    raw = snapshot.model_dump(mode="json")
    for item in raw["items"]:
        if item["item_id"] == item_id:
            for key, value in value_changes.items():
                item["values"][key] = value
    return DataSnapshot.model_validate(raw)


# -- requirements(): fx only when currency != base -----------------------------------------


def test_requirements_include_fx_for_a_foreign_currency_share():
    model = ShareFactorStress()
    ctx = context_of("EQ-TECH")  # USD share, RUB base
    needs = model.requirements(ctx, options())
    assert any(f.factor_id == "market.fx" for f in needs.factors)
    assert any(d.key == "fx" for d in needs.data)


def test_requirements_omit_fx_for_a_base_currency_share():
    model = ShareFactorStress()
    ctx = context_of("EQ-OIL")  # RUB share, RUB base
    needs = model.requirements(ctx, options())
    assert not any(f.factor_id == "market.fx" for f in needs.factors)
    assert not any(d.key == "fx" for d in needs.data)


def test_requirements_always_include_market_and_sector_factors():
    model = ShareFactorStress()
    ctx = context_of("EQ-OIL")
    needs = model.requirements(ctx, options())
    assert {f.factor_id for f in needs.factors} >= {"equity.market", "equity.sector"}


# -- validate(): price_currency_mismatch ----------------------------------------------------


def test_price_currency_mismatch_is_an_error():
    snapshot = edit_values(
        CASE.snapshot,
        "price:EQ-OIL:2026-09-11",
        price={"value": 100.0, "unit": "USD_per_unit", "evidence": [_evidence()]},
    )
    prepared, diagnostics = prepared_and_diagnostics("EQ-OIL", snapshot)
    codes = [d.code for d in diagnostics.items]
    assert "price_currency_mismatch" in codes
    assert diagnostics.blocking


# -- validate(): sensitivity_missing:<name> --------------------------------------------------


def test_sensitivity_missing_beta_market_is_an_error():
    raw = CASE.snapshot.model_dump(mode="json")
    for item in raw["items"]:
        if item["item_id"] == "sensitivity:EQ-OIL:2026-09-11":
            del item["values"]["beta_market"]
    snapshot = DataSnapshot.model_validate(raw)
    prepared, diagnostics = prepared_and_diagnostics("EQ-OIL", snapshot)
    codes = [d.code for d in diagnostics.items]
    assert "sensitivity_missing:beta_market" in codes


# -- validate(): dividend_horizon_mismatch --------------------------------------------------


def test_dividend_horizon_mismatch_is_an_error():
    raw = CASE.snapshot.model_dump(mode="json")
    for item in raw["items"]:
        if item["item_id"] == "dividend:EQ-OIL:2026-09-11":
            item["attributes"] = {**item.get("attributes", {}), "horizon_months": 6}
    snapshot = DataSnapshot.model_validate(raw)
    prepared, diagnostics = prepared_and_diagnostics("EQ-OIL", snapshot)
    codes = [d.code for d in diagnostics.items]
    assert "dividend_horizon_mismatch" in codes


# -- validate(): price_stale is a warning, not blocking --------------------------------------


def test_price_stale_is_a_warning_not_blocking():
    stale_date = (AS_OF - timedelta(days=30)).isoformat()
    snapshot = edit_item(CASE.snapshot, "price:EQ-OIL:2026-09-11", observed_on=stale_date)
    prepared, diagnostics = prepared_and_diagnostics("EQ-OIL", snapshot)
    stale = [d for d in diagnostics.items if d.code == "price_stale"]
    assert stale and stale[0].severity == "warning"
    assert prepared is not None
    assert not diagnostics.blocking


def _evidence():
    return {"kind": "document", "source_id": "S", "locator": "l", "fragment_sha256": "a" * 64}
