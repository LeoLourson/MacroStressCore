"""msa.reporting.builder: build() produces a Report whose every number traces to the tree."""

from dataclasses import replace

from msa.contracts.domain import Instrument, Party, Position, PositionContext
from msa.contracts.evidence import Evidence
from msa.engine.aggregation import aggregate_slices
from msa.engine.runner import run_batch
from msa.platform.registry import build as build_registry
from msa.plugin_sdk import ActionSpec, Plugin, RecommendationRule
from msa.reporting.builder import build as build_report
from msa.reporting.numbers import check_refs
from msa.reporting.tree import metric_tree
from tests import engine_helpers as h
from tests import minimal_plugin as mp

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


def with_rule(plugin, label):
    """``plugin`` with one rule on its default threshold that never observes a value."""
    observation, action = f"{plugin.plugin_id}.never", f"{plugin.plugin_id}.watch"
    return replace(
        plugin,
        rules=(
            RecommendationRule(f"{plugin.plugin_id}.R", label, observation, "ge", 0.0, (action,)),
        ),
        actions=(ActionSpec(action, "наблюдать"),),
        observations={observation: lambda result, context: None},
    )


def test_default_thresholds_name_only_the_rules_of_plugins_in_the_report():
    other = Plugin(plugin_id="other", version="1.0.0", sdk=">=1.0,<2.0", label="Другой")
    reg = build_registry(
        [
            with_rule(mp.plugin, "правило рассчитанного плагина"),
            with_rule(other, "правило другого плагина"),
            mp.MARKET_PLUGIN,
        ]
    )
    contexts = [context("POS1")]
    batch, portfolio = run_and_aggregate(contexts, reg)
    report = build_report(
        batch.results, portfolio, contexts, run_id="RUN1", graph=None, thresholds={}, registry=reg
    )
    line = next(x for x in report.summary.splitlines() if x.startswith("Пороги правил"))
    assert "правило рассчитанного плагина" in line
    assert "правило другого плагина" not in line


def test_an_assumption_on_the_event_text_names_the_text_not_its_hash():
    reg = registry()
    contexts = [context("POS1")]
    batch, portfolio = run_and_aggregate(contexts, reg)
    cited = {"source_id": "a" * 64, "locator": "p1/para1/s1", "fragment_sha256": "b" * 64}
    graph = {
        "event_id": "event",
        "nodes": [
            {"id": "event", "kind": "event", "label": "событие"},
            {"id": "channel", "kind": "channel", "label": "канал"},
        ],
        "edges": [
            {
                "src": "event",
                "dst": "channel",
                "sign": 1,
                "elasticity": {"family": "point", "value": 1.0},
                "lag_months": 0,
                "evidence": [{"kind": "document", **cited}],
            }
        ],
    }
    estimate = {"kind": "expert_assumption", "author": "LLM:m", "as_of": h.AS_OF, **cited}
    report = build_report(
        batch.results,
        portfolio,
        contexts,
        run_id="RUN1",
        graph=graph,
        thresholds={},
        registry=reg,
        scenario_evidence=[Evidence.model_validate(estimate)],
    )
    assert "- LLM:m, источник: текст события" in report.summary.splitlines()
