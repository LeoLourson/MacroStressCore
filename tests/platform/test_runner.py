"""msa.engine.runner: run_batch and idiosyncratic shock collection, on the minimal plugin."""

import numpy as np
import pytest

from msa.contracts.domain import Instrument, Party, Position, PositionContext
from msa.engine.runner import idiosyncratic_shocks, run_batch
from msa.platform.registry import build
from msa.plugin_sdk.model import Diagnostics, IdiosyncraticFactor

from . import engine_helpers as h
from . import minimal_plugin as mp

DUMMY_PARAMETERS = {"dummy": {"kind": "point", "value": 0.0, "unit": "fraction"}}


@pytest.fixture
def registry():
    return build([mp.plugin, mp.MARKET_PLUGIN])


def context(position_id, instrument_id, *, amount=10.0, issuer_id="P1"):
    issuer = Party(party_id=issuer_id, name="Issuer", okved="23.61")
    instrument = Instrument(
        instrument_id=instrument_id,
        instrument_type=mp.TYPE_ID,
        name="I",
        currency="RUB",
        issuer_id=issuer_id,
    )
    position = Position(
        position_id=position_id,
        instrument_id=instrument_id,
        params={"amount": h.amount_param(amount, "RUB")},
    )
    return PositionContext(
        portfolio_id="PF1",
        position=position,
        instrument=instrument,
        issuer=issuer,
    )


def run(contexts, registry, seed=1, points=64, replicates=8):
    return run_batch(
        contexts,
        h.empty_snapshot(),
        DUMMY_PARAMETERS,
        None,
        as_of=h.AS_OF,
        horizon=12,
        seed=seed,
        registry=registry,
        sector_of=lambda s: None,
        points=points,
        replicates=replicates,
    )


# -- idiosyncratic shocks shared by positions of the same instrument -----------------------------


def test_two_positions_of_the_same_instrument_share_identical_idiosyncratic_realisations(registry):
    ctx1 = context("POS1", "I1", amount=10.0)
    ctx2 = context("POS2", "I1", amount=25.0)  # same instrument, different size
    batch = run([ctx1, ctx2], registry)
    draws1 = np.asarray(batch.draws[("POS1", "market.pnl")])
    draws2 = np.asarray(batch.draws[("POS2", "market.pnl")])
    # In RUB with no FX movement, loss = -amount * idiosyncratic_noise, so if the noise
    # realisations are identical the two loss series are in exact proportion to amount.
    assert np.allclose(draws2, draws1 * (25.0 / 10.0))


def test_positions_of_different_instruments_do_not_share_the_shock(registry):
    ctx1 = context("POS1", "I1", amount=10.0)
    ctx2 = context("POS2", "I2", amount=10.0)  # different instrument, same amount
    batch = run([ctx1, ctx2], registry)
    draws1 = np.asarray(batch.draws[("POS1", "market.pnl")])
    draws2 = np.asarray(batch.draws[("POS2", "market.pnl")])
    assert not np.allclose(draws1, draws2)


# -- results ordered as given ----------------------------------------------------------------------


def test_results_are_ordered_as_the_contexts_were_given(registry):
    ctx2 = context("POS2", "I1")
    ctx1 = context("POS1", "I2")
    batch = run([ctx2, ctx1], registry)
    assert [r.position_id for r in batch.results] == ["POS2", "POS1"]


# -- draws split out of results --------------------------------------------------------------------


def test_draws_are_collected_into_batch_draws_and_excluded_from_the_result_dump(registry):
    ctx = context("POS1", "I1")
    batch = run([ctx], registry)
    result = batch.results[0]
    key = ("POS1", "market.pnl")
    assert key in batch.draws
    assert len(batch.draws[key]) == 8 * 64  # replicates * points
    dumped = result.model_dump(mode="json")
    assert "draws" not in dumped["contributions"][0]


def test_batch_draws_match_the_result_contributions_draws(registry):
    ctx = context("POS1", "I1")
    batch = run([ctx], registry)
    result = batch.results[0]
    assert batch.draws[("POS1", "market.pnl")] == result.contributions[0].draws


# -- idiosyncratic_shocks() -------------------------------------------------------------------


def shock(name="s1", subject="SUBJ", sigma=0.01):
    return IdiosyncraticFactor(name=name, subject=subject, sigma=sigma)


def test_idiosyncratic_shocks_collects_every_distinct_name():
    diagnostics = [
        Diagnostics(idiosyncratic=[shock("a")]),
        Diagnostics(idiosyncratic=[shock("b")]),
    ]
    shocks = idiosyncratic_shocks(diagnostics)
    assert [item.name for item in shocks] == ["a", "b"]


def test_idiosyncratic_shocks_deduplicates_identical_specs():
    diagnostics = [
        Diagnostics(idiosyncratic=[shock("a", subject="SUBJ", sigma=0.01)]),
        Diagnostics(idiosyncratic=[shock("a", subject="SUBJ", sigma=0.01)]),
    ]
    shocks = idiosyncratic_shocks(diagnostics)
    assert len(shocks) == 1


def test_idiosyncratic_shocks_rejects_two_different_specs_of_the_same_name():
    diagnostics = [
        Diagnostics(idiosyncratic=[shock("a", subject="SUBJ", sigma=0.01)]),
        Diagnostics(idiosyncratic=[shock("a", subject="SUBJ", sigma=0.02)]),
    ]
    with pytest.raises(ValueError, match="two different specifications of shock a"):
        idiosyncratic_shocks(diagnostics)


def test_idiosyncratic_shocks_of_empty_diagnostics_is_empty():
    assert idiosyncratic_shocks([Diagnostics(), Diagnostics()]) == []
