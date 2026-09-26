"""msa.reporting.tree: metric_node() and metric_tree()."""

from datetime import date

from msa.contracts.result import (
    CalculationResult,
    Coverage,
    MetricValue,
    PortfolioResult,
    PositionContribution,
    SliceResult,
)
from msa.contracts.risk import Quantiles
from msa.platform.registry import build
from msa.plugin_sdk.plugin import Plugin
from msa.reporting.tree import metric_node, metric_tree

SHA = "a" * 64


# -- metric_node ------------------------------------------------------------------------


def test_metric_node_with_value_only():
    m = MetricValue(metric_id="m", unit="fraction", value=1.5)
    assert metric_node(m) == {"unit": "fraction", "value": 1.5}


def test_metric_node_with_quantiles_no_es95():
    q = Quantiles(name="m", unit="fraction", p05=1.0, p50=2.0, p95=3.0)
    m = MetricValue(metric_id="m", unit="fraction", quantiles=q)
    node = metric_node(m)
    assert node == {"unit": "fraction", "p05": 1.0, "p50": 2.0, "p95": 3.0}


def test_metric_node_with_quantiles_and_es95():
    q = Quantiles(name="m", unit="fraction", p05=1.0, p50=2.0, p95=3.0, es95=4.0)
    m = MetricValue(metric_id="m", unit="fraction", quantiles=q)
    node = metric_node(m)
    assert node["es95"] == 4.0


def test_metric_node_with_both_value_and_quantiles():
    q = Quantiles(name="m", unit="fraction", p05=1.0, p50=2.0, p95=3.0)
    m = MetricValue(metric_id="m", unit="fraction", value=9.0, quantiles=q)
    node = metric_node(m)
    assert node["value"] == 9.0
    assert node["p50"] == 2.0


# -- metric_tree --------------------------------------------------------------------------


def result(position_id, *, metrics=None, execution="completed", status="ok", flags=None):
    return CalculationResult(
        position_id=position_id,
        instrument_id=position_id,
        instrument_type="t",
        plugin_id="test",
        plugin_version="1.0.0",
        model_id="test.m",
        model_version="1.0.0",
        as_of=date(2026, 1, 1),
        horizon=12,
        seed=1,
        execution=execution,
        status=status,
        scenario_id=SHA,
        metrics=metrics or {},
        flags=flags or [],
    )


def registry_with_tree_hook(hook=None):
    plugin = Plugin(
        plugin_id="test",
        version="1.0.0",
        sdk=">=1.0,<2.0",
        label="T",
        tree=hook,
    )
    return build([plugin])


def test_metric_tree_without_portfolio_has_no_portfolio_key():
    reg = registry_with_tree_hook()
    tree = metric_tree([result("POS1")], None, registry=reg)
    assert "portfolio" not in tree
    assert tree["positions"]["POS1"]["metrics"] == {}


def test_metric_tree_positions_are_sorted_by_id():
    reg = registry_with_tree_hook()
    tree = metric_tree([result("POS2"), result("POS1")], None, registry=reg)
    assert list(tree["positions"]) == ["POS1", "POS2"]


def test_metric_tree_includes_metric_nodes():
    reg = registry_with_tree_hook()
    metrics = {"m": MetricValue(metric_id="m", unit="fraction", value=1.0)}
    tree = metric_tree([result("POS1", metrics=metrics)], None, registry=reg)
    assert tree["positions"]["POS1"]["metrics"]["m"] == {"unit": "fraction", "value": 1.0}


def test_metric_tree_applies_the_plugin_tree_hook_for_completed_results():
    def hook(r, context):
        return {"details_tree": {"note": "hello", "ctx": context.get("x")}}

    reg = registry_with_tree_hook(hook)
    tree = metric_tree([result("POS1")], None, registry=reg, context={"x": 42})
    assert tree["positions"]["POS1"]["details_tree"] == {"note": "hello", "ctx": 42}


def test_metric_tree_skips_the_tree_hook_for_a_result_that_did_not_complete():
    def hook(r, context):
        return {"details_tree": {"note": "should not appear"}}

    reg = registry_with_tree_hook(hook)
    r = result("POS1", execution="not_run", status="needs_review", flags=["x"])
    tree = metric_tree([r], None, registry=reg)
    assert "details_tree" not in tree["positions"]["POS1"]


def test_metric_tree_skips_hook_for_a_result_of_an_unregistered_plugin():
    reg = registry_with_tree_hook()
    r = result("POS1").model_copy(update={"plugin_id": "no_such_plugin"})
    tree = metric_tree([r], None, registry=reg)
    assert tree["positions"]["POS1"] == {"metrics": {}}


# -- metric_tree: portfolio ---------------------------------------------------------------


def portfolio_result():
    slice_result = SliceResult(
        slice_id="test.slice",
        measure="loss",
        unit="RUB_million",
        status="incomplete",
        loss_quantiles=Quantiles(
            name="test.slice", unit="RUB_million", p05=1.0, p50=2.0, p95=3.0, es95=3.0
        ),
        mean_loss=2.0,
        value_at_risk_95=3.0,
        expected_shortfall_95=3.0,
        coverage=Coverage(basis="market_value", covered_share=0.8, limit=0.05),
        herfindahl=0.5,
        included=["POS1"],
        flags=["coverage_below_limit"],
        contributions=[
            PositionContribution(
                position_id="POS1",
                mean_loss=2.0,
                expected_shortfall_contribution=3.0,
                p95_standalone=3.0,
            )
        ],
        sum_of_individual_p95=3.0,
    )
    return PortfolioResult(
        run_id="RUN1",
        as_of=date(2026, 1, 1),
        horizon=12,
        seed=1,
        scenario_id=SHA,
        macro_draws_sha256=SHA,
        slices={"test.slice": slice_result},
        status="ok",
    )


def test_metric_tree_with_portfolio_reports_slice_status_and_coverage_percent():
    reg = registry_with_tree_hook()
    tree = metric_tree([result("POS1")], portfolio_result(), registry=reg)
    slice_tree = tree["portfolio"]["slices"]["test.slice"]
    assert tree["portfolio"]["status"] == "ok"
    assert slice_tree["covered_percent"] == 80.0


def test_metric_tree_portfolio_contributions_keyed_by_position_id():
    reg = registry_with_tree_hook()
    tree = metric_tree([result("POS1")], portfolio_result(), registry=reg)
    contributions = tree["portfolio"]["slices"]["test.slice"]["contributions"]
    assert set(contributions) == {"POS1"}
    assert contributions["POS1"]["mean_loss"] == 2.0


def test_metric_tree_accepts_a_portfolio_dict_too():
    reg = registry_with_tree_hook()
    dumped = portfolio_result().model_dump(mode="json")
    tree = metric_tree([result("POS1")], dumped, registry=reg)
    assert tree["portfolio"]["status"] == "ok"
