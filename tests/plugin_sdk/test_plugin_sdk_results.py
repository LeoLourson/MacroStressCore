"""msa.plugin_sdk.results: envelope(), quantiles(), distribution() and scalar()."""

from datetime import date

import numpy as np
import pytest

from msa.contracts.domain import Instrument, Position, PositionContext
from msa.engine.scenario_set import Realisations, scenario_set_from_parameters
from msa.plugin_sdk.model import CalculationContext, PreparedInputs
from msa.plugin_sdk.results import distribution, envelope, quantiles, scalar

from tests import minimal_plugin as mp


def prepared():
    instrument = Instrument(instrument_id="I1", instrument_type=mp.TYPE_ID, name="I1")
    ctx = PositionContext(
        portfolio_id="PF1",
        position=Position(position_id="POS1", instrument_id="I1"),
        instrument=instrument,
        issuer=None,
    )
    return PreparedInputs(
        context=ctx,
        model_id=mp.MODEL_ID,
        as_of=date(2026, 1, 1),
        horizon=12,
        snapshot_id="SNAP1",
    )


def context():
    scenario_set = scenario_set_from_parameters(
        {"dummy": {"kind": "point", "value": 0.0, "unit": "fraction"}},
        points=64,
        replicates=8,
    )
    realisations = Realisations(
        scenario_set=scenario_set,
        seed=1,
        as_of=date(2026, 1, 1),
        horizon=12,
    )
    return CalculationContext(
        as_of=date(2026, 1, 1),
        horizon=12,
        seed=1,
        base_currency="RUB",
        scenario=realisations,
        snapshot_id="SNAP1",
        scenario_set=scenario_set,
    )


# -- quantiles() ----------------------------------------------------------------------------


def test_quantiles_without_tail_has_no_es95():
    draws = np.arange(1.0, 101.0)
    q = quantiles("m", "fraction", draws)
    assert q.p50 == pytest.approx(50.5, abs=1.0)
    assert q.es95 is None


def test_quantiles_with_tail_reports_es95_at_least_p95():
    draws = np.arange(1.0, 101.0)
    q = quantiles("m", "fraction", draws, tail=True)
    assert q.es95 is not None
    assert q.es95 >= q.p95


def test_quantiles_flattens_a_2d_array():
    draws = np.array([[1.0, 2.0], [3.0, 4.0]])
    q = quantiles("m", "fraction", draws)
    assert q.p50 == pytest.approx(2.5)


# -- distribution() / scalar() ---------------------------------------------------------------


def test_distribution_carries_the_given_central_value():
    draws = np.array([1.0, 2.0, 3.0])
    m = distribution("m", "fraction", draws, value=9.0)
    assert m.value == 9.0
    assert m.quantiles is not None
    assert m.quantiles.p50 == 2.0


def test_distribution_without_value_has_none_value():
    draws = np.array([1.0, 2.0, 3.0])
    m = distribution("m", "fraction", draws)
    assert m.value is None


def test_scalar_has_value_and_no_quantiles():
    m = scalar("m", "fraction", 5)
    assert m.value == 5.0
    assert m.quantiles is None
    assert isinstance(m.value, float)


# -- envelope() -------------------------------------------------------------------------------


def test_envelope_fills_identity_from_prepared_and_context():
    model = mp.CashModel()
    p, c = prepared(), context()
    result = envelope(
        p,
        c,
        model,
        plugin_id="minimal",
        plugin_version="1.0.0",
        status="ok",
        metrics={},
        contributions=[],
    )
    assert result.position_id == "POS1"
    assert result.instrument_id == "I1"
    assert result.instrument_type == mp.TYPE_ID
    assert result.plugin_id == "minimal"
    assert result.model_id == mp.MODEL_ID
    assert result.model_version == model.version
    assert result.execution == "completed"
    assert result.scenario_id == c.scenario.scenario_id
    assert result.macro_draws_sha256 == c.scenario.macro_draws_sha256
    assert len(result.code_sha256) == 64


def test_envelope_extra_fields_override_defaults():
    model = mp.CashModel()
    p, c = prepared(), context()
    result = envelope(
        p,
        c,
        model,
        plugin_id="minimal",
        plugin_version="1.0.0",
        status="ok",
        metrics={},
        contributions=[],
        flags=["a_flag"],
    )
    assert result.flags == ["a_flag"]
