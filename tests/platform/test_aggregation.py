"""msa.engine.aggregation: portfolio slices built from positions' contributions."""

from datetime import date

import numpy as np
import pytest

from msa.contracts.result import AggregationContribution, CalculationResult
from msa.engine.aggregation import UNKNOWN_EXPOSURE_FLAG, aggregate_slices
from msa.platform.registry import build
from msa.plugin_sdk.plugin import Plugin
from msa.plugin_sdk.specs import BASE_MONEY, SliceSpec

SHA = "a" * 64
AS_OF = date(2026, 1, 1)
SLICE = "test.slice"


def registry(slice_id=SLICE, coverage_limit=0.05, exposure_basis="market_value"):
    plugin = Plugin(
        plugin_id="test",
        version="1.0.0",
        sdk=">=1.0,<2.0",
        label="T",
        slices=(
            SliceSpec(
                slice_id=slice_id,
                label="S",
                measure_label="loss",
                exposure_basis=exposure_basis,
                exposure_label="E",
                unit=BASE_MONEY,
                coverage_limit=coverage_limit,
            ),
        ),
    )
    return build([plugin])


def contribution(
    *,
    slice_id=SLICE,
    unit="RUB_million",
    horizon=12,
    scenario_id=SHA,
    exposure=10.0,
    admission="included",
    has_draws=True,
):
    return AggregationContribution(
        slice_id=slice_id,
        measure="loss",
        unit=unit,
        horizon=horizon,
        scenario_id=scenario_id,
        exposure=exposure,
        exposure_basis="market_value",
        admission=admission,
        draws=[1.0, 2.0] if has_draws else None,
    )


def calc_result(
    position_id,
    *,
    status="ok",
    flags=None,
    contributions=None,
    execution="completed",
    horizon=12,
    scenario_id=SHA,
):
    # The result's own horizon/scenario_id must match its contributions (CalculationResult's
    # own consistency rule); a mismatch with the *run*'s horizon/scenario_id is what
    # aggregate_slices treats as incompatible, so callers testing that pass them here too.
    return CalculationResult(
        position_id=position_id,
        instrument_id=position_id,
        instrument_type="t",
        plugin_id="test",
        plugin_version="1.0.0",
        model_id="test.m",
        model_version="1.0.0",
        as_of=AS_OF,
        horizon=horizon,
        seed=1,
        execution=execution,
        status=status,
        scenario_id=scenario_id,
        flags=flags or [],
        contributions=contributions or [],
    )


def aggregate(results, *, draws=None, exposures=None, reg=None, base_currency="RUB"):
    return aggregate_slices(
        "RUN1",
        results,
        draws=draws or {},
        exposures=exposures or {},
        registry=reg or registry(),
        base_currency=base_currency,
        as_of=AS_OF,
        horizon=12,
        seed=1,
        scenario_id=SHA,
        macro_draws_sha256=SHA,
    )


# -- sums draws by realisation --------------------------------------------------------------


def test_sums_draws_by_realisation_within_a_slice():
    results = [
        calc_result("POS1", contributions=[contribution()]),
        calc_result("POS2", contributions=[contribution()]),
    ]
    draws = {("POS1", SLICE): [1.0, 2.0, 3.0, 4.0], ("POS2", SLICE): [10.0, 20.0, 30.0, 40.0]}
    exposures = {"POS1": {SLICE: 30.0}, "POS2": {SLICE: 70.0}}
    portfolio = aggregate(results, draws=draws, exposures=exposures)
    slice_result = portfolio.slices[SLICE]
    assert slice_result.mean_loss == pytest.approx(np.mean([11.0, 22.0, 33.0, 44.0]))


# -- coverage by exposure --------------------------------------------------------------------


def test_coverage_is_full_when_every_position_included():
    results = [
        calc_result("POS1", contributions=[contribution(exposure=30.0)]),
        calc_result("POS2", contributions=[contribution(exposure=70.0)]),
    ]
    draws = {("POS1", SLICE): [1.0, 2.0], ("POS2", SLICE): [3.0, 4.0]}
    exposures = {"POS1": {SLICE: 30.0}, "POS2": {SLICE: 70.0}}
    portfolio = aggregate(results, draws=draws, exposures=exposures)
    assert portfolio.slices[SLICE].coverage.covered_share == pytest.approx(1.0)
    assert portfolio.slices[SLICE].status == "ok"


def test_coverage_drops_when_a_position_is_excluded():
    results = [
        calc_result("POS1", contributions=[contribution(exposure=30.0)]),
        calc_result("POS2", contributions=[contribution(exposure=70.0)]),
        calc_result(
            "POS3",
            status="invalid",
            flags=["broken"],
            contributions=[
                contribution(exposure=50.0, admission="excluded:broken", has_draws=False)
            ],
        ),
    ]
    draws = {("POS1", SLICE): [1.0, 2.0], ("POS2", SLICE): [3.0, 4.0]}
    exposures = {"POS1": {SLICE: 30.0}, "POS2": {SLICE: 70.0}, "POS3": {SLICE: 50.0}}
    portfolio = aggregate(results, draws=draws, exposures=exposures)
    slice_result = portfolio.slices[SLICE]
    assert slice_result.coverage.covered_share == pytest.approx(100.0 / 150.0)
    # 1 - coverage = 1/3 > the default 0.05 limit, so the slice is incomplete.
    assert slice_result.status == "incomplete"


# -- admitted:<rule> ---------------------------------------------------------------------------


def test_admitted_rule_contribution_enters_and_adds_flags():
    results = [
        calc_result(
            "POS1",
            status="needs_review",
            flags=["review_me"],
            contributions=[contribution(admission="admitted:R1")],
        ),
    ]
    draws = {("POS1", SLICE): [1.0, 2.0]}
    exposures = {"POS1": {SLICE: 10.0}}
    portfolio = aggregate(results, draws=draws, exposures=exposures)
    slice_result = portfolio.slices[SLICE]
    assert slice_result.status == "needs_review"
    assert "POS1" in slice_result.included
    assert "inclusion_rule:R1" in slice_result.flags
    assert "included_by_rule:POS1" in slice_result.flags


# -- excluded:* ----------------------------------------------------------------------------------


def test_excluded_contribution_does_not_enter():
    results = [
        calc_result(
            "POS1",
            status="incomplete",
            flags=["not_material"],
            contributions=[contribution(admission="excluded:not_material", has_draws=False)],
        ),
    ]
    exposures = {"POS1": {SLICE: 10.0}}
    portfolio = aggregate(results, exposures=exposures)
    slice_result = portfolio.slices[SLICE]
    assert slice_result.included == []
    assert slice_result.excluded[0].position_id == "POS1"
    assert slice_result.excluded[0].reason == "not_material"


# -- unknown exposure -----------------------------------------------------------------------------


def test_unknown_exposure_makes_the_slice_incomplete():
    results = [calc_result("POS1", contributions=[contribution(exposure=None)])]
    draws = {("POS1", SLICE): [1.0, 2.0]}
    portfolio = aggregate(results, draws=draws, exposures={})
    slice_result = portfolio.slices[SLICE]
    assert slice_result.status == "incomplete"
    assert UNKNOWN_EXPOSURE_FLAG in slice_result.flags
    assert slice_result.coverage.unknown_exposure == ["POS1"]


# -- incompatible contribution ---------------------------------------------------------------------


def test_incompatible_unit_is_excluded_as_invalid():
    results = [calc_result("POS1", contributions=[contribution(unit="fraction")])]
    exposures = {"POS1": {SLICE: 10.0}}
    portfolio = aggregate(results, exposures=exposures)
    slice_result = portfolio.slices[SLICE]
    assert "POS1" not in slice_result.included
    excluded = slice_result.excluded[0]
    assert excluded.status == "invalid"
    assert excluded.reason.startswith("incompatible:")


def test_incompatible_horizon_is_excluded_as_invalid():
    # The run itself is 12 months; this result (and its matching contribution) is 6.
    results = [calc_result("POS1", horizon=6, contributions=[contribution(horizon=6)])]
    portfolio = aggregate(results, exposures={"POS1": {SLICE: 10.0}})
    assert portfolio.slices[SLICE].excluded[0].status == "invalid"


def test_incompatible_scenario_is_excluded_as_invalid():
    other_scenario = "b" * 64
    results = [
        calc_result(
            "POS1",
            scenario_id=other_scenario,
            contributions=[contribution(scenario_id=other_scenario)],
        )
    ]
    portfolio = aggregate(results, exposures={"POS1": {SLICE: 10.0}})
    assert portfolio.slices[SLICE].excluded[0].status == "invalid"


# -- positions outside any slice -------------------------------------------------------------------


def test_position_outside_any_slice_is_not_aggregated():
    results = [calc_result("POS1", contributions=[]), calc_result("POS2", contributions=[])]
    portfolio = aggregate(results)
    assert {e.position_id for e in portfolio.not_aggregated} == {"POS1", "POS2"}
    assert "positions_outside_slices" in portfolio.flags
    assert portfolio.slices == {}


# -- duplicate position ids ------------------------------------------------------------------------


def test_duplicate_position_results_are_rejected():
    results = [calc_result("POS1"), calc_result("POS1")]
    with pytest.raises(ValueError, match="duplicate position result"):
        aggregate(results)


# -- slices never mixed ---------------------------------------------------------------------


def test_two_slices_are_aggregated_independently():
    reg = registry_two_slices()
    results = [
        calc_result(
            "POS1",
            contributions=[
                contribution(slice_id="test.a"),
                contribution(slice_id="test.b"),
            ],
        ),
    ]
    draws = {("POS1", "test.a"): [1.0, 2.0], ("POS1", "test.b"): [100.0, 200.0]}
    exposures = {"POS1": {"test.a": 10.0, "test.b": 10.0}}
    portfolio = aggregate(results, draws=draws, exposures=exposures, reg=reg)
    assert portfolio.slices["test.a"].mean_loss == pytest.approx(1.5)
    assert portfolio.slices["test.b"].mean_loss == pytest.approx(150.0)


def registry_two_slices():
    plugin = Plugin(
        plugin_id="test",
        version="1.0.0",
        sdk=">=1.0,<2.0",
        label="T",
        slices=(
            SliceSpec(
                slice_id="test.a",
                label="A",
                measure_label="loss",
                exposure_basis="market_value",
                exposure_label="E",
                unit=BASE_MONEY,
            ),
            SliceSpec(
                slice_id="test.b",
                label="B",
                measure_label="loss",
                exposure_basis="market_value",
                exposure_label="E",
                unit=BASE_MONEY,
            ),
        ),
    )
    return build([plugin])
