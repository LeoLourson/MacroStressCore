"""msa.reporting.builder: build() produces a Report whose every number traces to the tree."""

from msa.contracts.domain import Instrument, Party, Position, PositionContext
from msa.engine.aggregation import aggregate_slices
from msa.engine.runner import run_batch
from msa.platform.registry import build as build_registry
from msa.reporting.builder import build as build_report
from msa.reporting.numbers import check_refs
from msa.reporting.tree import metric_tree

from . import engine_helpers as h
from . import minimal_plugin as mp

DUMMY_PARAMETERS = {"dummy": {"kind": "point", "value": 0.0, "unit": "fraction"}}


def registry():
    return build_registry([mp.plugin, mp.MARKET_PLUGIN])


def context(position_id, *, amount=10.0):
    issuer = Party(party_id="P1", name="Issuer", okved="23.61")
    instrument = Instrument(
        instrument_id=position_id,
        instrument_type=mp.TYPE_ID,
        name="I",
        currency="RUB",
        issuer_id="P1",
    )
    position = Position(
        position_id=position_id,
        instrument_id=position_id,
        params={"amount": h.amount_param(amount, "RUB")},
    )
    return PositionContext(
        portfolio_id="PF1",
        position=position,
        instrument=instrument,
        issuer=issuer,
    )


def run_and_aggregate(contexts, reg):
    batch = run_batch(
        contexts,
        h.empty_snapshot(),
        DUMMY_PARAMETERS,
        None,
        as_of=h.AS_OF,
        horizon=12,
        seed=1,
        registry=reg,
        sector_of=lambda s: None,
        points=64,
        replicates=8,
    )
    portfolio = aggregate_slices(
        "RUN1",
        batch.results,
        draws=batch.draws,
        exposures=batch.exposures,
        registry=reg,
        base_currency="RUB",
        as_of=h.AS_OF,
        horizon=12,
        seed=1,
        scenario_id=batch.realisations.scenario_id,
        macro_draws_sha256=batch.realisations.macro_draws_sha256,
    )
    return batch, portfolio


def test_build_report_every_cited_number_resolves_in_the_metric_tree():
    reg = registry()
    contexts = [context("POS1")]
    batch, portfolio = run_and_aggregate(contexts, reg)
    report = build_report(
        batch.results,
        portfolio,
        contexts,
        run_id="RUN1",
        graph=None,
        thresholds={},
        registry=reg,
        names={"POS1": "Позиция один"},
    )
    tree = metric_tree(report.results, report.portfolio, registry=reg)
    refs = [n.model_dump(mode="json") for n in report.numbers]
    assert check_refs(report.summary, refs, tree) == []
    assert report.numbers  # the summary actually cites numbers


def test_build_report_summary_mentions_coverage_of_the_slice():
    reg = registry()
    contexts = [context("POS1")]
    batch, portfolio = run_and_aggregate(contexts, reg)
    report = build_report(
        batch.results,
        portfolio,
        contexts,
        run_id="RUN1",
        graph=None,
        thresholds={},
        registry=reg,
    )
    assert "Расчётом охвачено" in report.summary
    assert reg.slices[mp.SLICE_ID].label in report.summary


def test_build_report_without_recommendations_states_none_assigned():
    reg = registry()
    contexts = [context("POS1")]
    batch, portfolio = run_and_aggregate(contexts, reg)
    report = build_report(
        batch.results,
        portfolio,
        contexts,
        run_id="RUN1",
        graph=None,
        thresholds={},
        registry=reg,
    )
    assert report.recommendations == []
    assert "Не назначены." in report.summary


def test_build_report_mode_is_recorded():
    reg = registry()
    contexts = [context("POS1")]
    batch, portfolio = run_and_aggregate(contexts, reg)
    report = build_report(
        batch.results,
        portfolio,
        contexts,
        run_id="RUN1",
        graph=None,
        thresholds={},
        registry=reg,
        mode="demo",
    )
    assert report.mode == "demo"


def test_build_report_result_matches_input_position():
    reg = registry()
    contexts = [context("POS1")]
    batch, portfolio = run_and_aggregate(contexts, reg)
    report = build_report(
        batch.results,
        portfolio,
        contexts,
        run_id="RUN1",
        graph=None,
        thresholds={},
        registry=reg,
    )
    assert [r.position_id for r in report.results] == ["POS1"]
    assert report.portfolio.slices[mp.SLICE_ID].included == ["POS1"]
