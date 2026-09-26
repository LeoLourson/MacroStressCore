"""msa.engine.fx: pairs, requirements, spot rates and log changes of a currency pair."""

from datetime import date

import numpy as np
import pytest

from msa.contracts.domain import Instrument, Position, PositionContext
from msa.contracts.evidence import Evidence, Parameter
from msa.contracts.snapshot import SnapshotItem
from msa.engine.fx import FX_FACTOR, FX_KEY, factor, log_change, pair, requirement, spot
from msa.plugin_sdk.model import PreparedInputs


def test_pair_formats_currency_over_base():
    assert pair("USD", "RUB") == "USD/RUB"


def test_requirement_is_none_for_the_base_currency():
    assert requirement("RUB", "RUB") is None


def test_requirement_names_fx_rate_of_the_pair():
    req = requirement("USD", "RUB")
    assert req.kind == "fx_rate"
    assert req.subject == "USD/RUB"
    assert req.key == FX_KEY


def test_factor_is_none_for_the_base_currency():
    assert factor("RUB", "RUB") is None


def test_factor_names_market_fx_with_the_pair_as_key():
    f = factor("USD", "RUB")
    assert f.factor_id == FX_FACTOR
    assert f.key == "USD/RUB"


# -- spot() -------------------------------------------------------------------------------


def prepared_with(data):
    instrument = Instrument(
        instrument_id="I1",
        instrument_type="minimal_cash",
        name="I1",
        currency="USD",
    )
    context = PositionContext(
        portfolio_id="PF1",
        position=Position(position_id="POS1", instrument_id="I1"),
        instrument=instrument,
        issuer=None,
    )
    return PreparedInputs(
        context=context,
        model_id="m",
        as_of=date(2026, 1, 1),
        horizon=12,
        snapshot_id="S",
        data=data,
    )


def fx_item(rate=92.5):
    evidence = [Evidence(kind="document", source_id="S", locator="l", fragment_sha256="a" * 64)]
    return SnapshotItem(
        item_id="fx:USD/RUB",
        kind="fx_rate",
        subject="USD/RUB",
        observed_on=date(2026, 1, 1),
        values={"rate": Parameter(value=rate, unit="ratio", evidence=evidence)},
    )


def test_spot_is_one_for_base_currency():
    assert spot(prepared_with({}), "RUB", "RUB") == 1.0


def test_spot_reads_the_rate_from_the_prepared_fx_item():
    p = prepared_with({FX_KEY: fx_item(92.5)})
    assert spot(p, "USD", "RUB") == 92.5


def test_spot_is_none_when_item_absent():
    assert spot(prepared_with({}), "USD", "RUB") is None


def test_spot_is_none_when_item_present_but_lacks_rate_value():
    evidence = [Evidence(kind="document", source_id="S", locator="l", fragment_sha256="a" * 64)]
    item = SnapshotItem(
        item_id="fx:USD/RUB",
        kind="fx_rate",
        subject="USD/RUB",
        observed_on=date(2026, 1, 1),
        values={"other": Parameter(value=1.0, unit="ratio", evidence=evidence)},
    )
    p = prepared_with({FX_KEY: item})
    assert spot(p, "USD", "RUB") is None


# -- log_change() -------------------------------------------------------------------------


def scenario_stub(names_to_draws, replicates=2, points=4):
    """A minimal ``ScenarioView`` stand-in: name -> (factor_id, key, {"central", "draws"})."""

    class Scenario:
        @property
        def replicates(self):
            return replicates

        @property
        def points(self):
            return points

        def parameters_for(self, factor_id, key=None):
            return sorted(
                name
                for name, (fid, k, _) in names_to_draws.items()
                if fid == factor_id and (key is None or k == key)
            )

        def central(self, name):
            return names_to_draws[name][2]["central"]

        def draws(self, name):
            return names_to_draws[name][2]["draws"]

    return Scenario()


def test_log_change_zero_for_base_currency():
    scenario = scenario_stub({})
    central, draws = log_change(scenario, "RUB", "RUB", flags=[])
    assert central == 0.0
    assert np.array_equal(draws, np.zeros((2, 4)))


def test_log_change_flags_pair_not_in_scenario():
    scenario = scenario_stub({})
    flags = []
    central, draws = log_change(scenario, "USD", "RUB", flags=flags)
    assert central == 0.0
    assert np.array_equal(draws, np.zeros((2, 4)))
    assert flags == [f"factor_not_in_scenario:{FX_FACTOR}:USD/RUB"]


def test_log_change_does_not_duplicate_the_flag():
    scenario = scenario_stub({})
    flags = [f"factor_not_in_scenario:{FX_FACTOR}:USD/RUB"]
    log_change(scenario, "USD", "RUB", flags=flags)
    assert flags.count(f"factor_not_in_scenario:{FX_FACTOR}:USD/RUB") == 1


def test_log_change_sums_multiple_parameters_of_the_same_pair():
    draws_a = np.full((2, 4), 0.1)
    draws_b = np.full((2, 4), 0.05)
    scenario = scenario_stub(
        {
            "usd_a": (FX_FACTOR, "USD/RUB", {"central": 0.1, "draws": draws_a}),
            "usd_b": (FX_FACTOR, "USD/RUB", {"central": 0.05, "draws": draws_b}),
        }
    )
    central, draws = log_change(scenario, "USD", "RUB", flags=[])
    assert central == pytest.approx(0.15)
    assert np.allclose(draws, 0.15)


def test_log_change_ignores_parameters_of_another_pair():
    draws_a = np.full((2, 4), 0.1)
    scenario = scenario_stub(
        {
            "usd": (FX_FACTOR, "USD/RUB", {"central": 0.1, "draws": draws_a}),
            "eur": (FX_FACTOR, "EUR/RUB", {"central": 99.0, "draws": np.full((2, 4), 99.0)}),
        }
    )
    central, draws = log_change(scenario, "USD", "RUB", flags=[])
    assert central == pytest.approx(0.1)
    assert np.allclose(draws, 0.1)
