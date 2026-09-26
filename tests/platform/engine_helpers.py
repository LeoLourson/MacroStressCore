"""Shared builders for the engine tests: contexts, snapshots and calculation contexts.

Kept separate from ``minimal_plugin.py`` so that file stays a plain plugin declaration.
"""

from datetime import date

from msa.contracts.domain import Instrument, Party, Position, PositionContext
from msa.contracts.evidence import Evidence, Parameter
from msa.contracts.snapshot import DataSnapshot, SnapshotItem
from msa.engine.dispatch import prepare as dispatch_prepare
from msa.engine.scenario_set import Realisations, scenario_set_from_parameters
from msa.engine.snapshot import SnapshotIndex
from msa.plugin_sdk.model import CalculationContext, RunOptions

from . import minimal_plugin as mp

AS_OF = date(2026, 1, 1)
POINTS = 64
REPLICATES = 8


def evidence():
    return [Evidence(kind="document", source_id="S", locator="l", fragment_sha256="a" * 64)]


def amount_param(value, currency):
    return {
        "value": value,
        "unit": f"{currency}_million",
        "evidence": [
            {"kind": "document", "source_id": "S", "locator": "l", "fragment_sha256": "a" * 64}
        ],
    }


def cash_context(
    *,
    position_id="POS1",
    instrument_id="I1",
    currency="RUB",
    issuer_id="P1",
    amount=10.0,
    schema_version="1",
    params_override=None,
    model_id=None,
    instrument_type=mp.TYPE_ID,
):
    issuer = Party(party_id=issuer_id, name="Issuer", okved="23.61") if issuer_id else None
    instrument = Instrument(
        instrument_id=instrument_id,
        instrument_type=instrument_type,
        name="I",
        currency=currency,
        issuer_id=issuer_id,
    )
    if params_override is not None:
        params = params_override
    else:
        params = {"amount": amount_param(amount, currency)}
    position = Position(
        position_id=position_id,
        instrument_id=instrument_id,
        params=params,
        schema_version=schema_version,
        model_id=model_id,
    )
    return PositionContext(
        portfolio_id="PF1",
        position=position,
        instrument=instrument,
        issuer=issuer,
    )


def run_options(base_currency="RUB", as_of=AS_OF, horizon=12, options=None):
    return RunOptions(
        as_of=as_of,
        horizon=horizon,
        base_currency=base_currency,
        options=options or {},
    )


def fx_snapshot(rate=90.0, observed_on=AS_OF, pair="USD/RUB", snapshot_as_of=None):
    item = SnapshotItem(
        item_id="fx1",
        kind="fx_rate",
        subject=pair,
        observed_on=observed_on,
        values={"rate": Parameter(value=rate, unit="ratio", evidence=evidence())},
    )
    return DataSnapshot(
        snapshot_id="SNAP1",
        as_of=snapshot_as_of or max(AS_OF, observed_on),
        label="L",
        items=[item],
    )


def empty_snapshot():
    return DataSnapshot(snapshot_id="SNAP1", as_of=AS_OF, label="L", items=[])


def prepare_with(ctx, options, registry, items=()):
    """``dispatch.prepare`` with no sector lookup, against a snapshot of just ``items``."""
    index = SnapshotIndex("SNAP1", items)
    return dispatch_prepare(ctx, options, index, registry, sector_of=lambda s: None)


def calculation_context(
    diagnostics,
    *,
    parameters=None,
    seed=1,
    points=POINTS,
    replicates=REPLICATES,
    base_currency="RUB",
    horizon=12,
    snapshot_id="SNAP1",
    scenario_set=None,
):
    """A ``CalculationContext`` whose scenario set carries every idiosyncratic shock the
    model's ``validate()`` declared, so ``model.calculate()`` can read them."""
    parameters = parameters or {"dummy": {"kind": "point", "value": 0.0, "unit": "fraction"}}
    scenario_set = scenario_set or scenario_set_from_parameters(
        parameters, points=points, replicates=replicates
    )
    scenario_set = scenario_set.with_idiosyncratic(diagnostics.idiosyncratic)
    realisations = Realisations(scenario_set=scenario_set, seed=seed, as_of=AS_OF, horizon=horizon)
    return CalculationContext(
        as_of=AS_OF,
        horizon=horizon,
        seed=seed,
        base_currency=base_currency,
        scenario=realisations,
        snapshot_id=snapshot_id,
        scenario_set=scenario_set,
    )
