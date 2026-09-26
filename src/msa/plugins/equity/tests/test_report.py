"""Equity plugin: report observations (equity.E1/E2 rule inputs) and the details -> tree view."""

from datetime import date

from msa.contracts.result import CalculationResult, MetricValue
from msa.contracts.risk import Quantiles
from msa.platform.registry import registry
from msa.plugins.equity.report import RULES, observe_loss_share, observe_pnl, tree
from msa.reporting.recommendations import apply

SHA = "a" * 64


def details(value_current=100.0, loss_p95=30.0):
    return {
        "currency": "RUB",
        "base_currency": "RUB",
        "price": 250.0,
        "price_date": "2026-09-11",
        "fx": 1.0,
        "quantity": 400.0,
        "beta_market": 1.1,
        "beta_sector": 0.9,
        "residual_sigma": 0.2,
        "dividend_per_share": 5.0,
        "value_current": value_current,
        "central": {
            "log_return": 0.0,
            "price": 250.0,
            "fx": 1.0,
            "value": value_current,
            "dividends": 2.0,
            "pnl": -20.0,
            "pnl_vs_base": -22.0,
        },
        "factor_contributions": [
            {"factor_id": "equity.market", "key": "MOEX", "label": "Рынок", "contribution": -15.0},
            {
                "factor_id": "equity.sector",
                "key": "oil_gas",
                "label": "Отрасль",
                "contribution": -5.0,
            },
        ],
        "loss_histogram": {"edges": [0.0, 10.0, 20.0], "counts": [3, 2]},
        "conventions": [],
    }


def result(
    position_id="POS1", *, value_current=100.0, loss_p95=30.0, pnl_p50=-20.0, execution="completed"
):
    return CalculationResult(
        position_id=position_id,
        instrument_id=position_id,
        instrument_type="common_stock",
        plugin_id="equity",
        plugin_version="1.0.0",
        model_id="equity.factor_stress.v1",
        model_version="1.0.0",
        as_of=date(2026, 1, 1),
        horizon=12,
        seed=1,
        execution=execution,
        status="ok",
        scenario_id=SHA,
        metrics={
            "equity.loss": MetricValue(
                metric_id="equity.loss",
                unit="RUB_million",
                quantiles=Quantiles(
                    name="equity.loss",
                    unit="RUB_million",
                    p05=loss_p95 * 0.2,
                    p50=loss_p95 * 0.6,
                    p95=loss_p95,
                    es95=loss_p95 + 5,
                ),
            ),
            "equity.pnl": MetricValue(
                metric_id="equity.pnl",
                unit="RUB_million",
                quantiles=Quantiles(
                    name="equity.pnl", unit="RUB_million", p05=-30.0, p50=pnl_p50, p95=-5.0
                ),
            ),
        },
        details=details(value_current=value_current, loss_p95=loss_p95),
    )


# -- observe_loss_share / observe_pnl --------------------------------------------------------


def test_observe_loss_share_returns_percentage_of_current_value():
    r = result(value_current=100.0, loss_p95=30.0)
    value, path = observe_loss_share(r, {})
    assert value == 30.0
    assert path == "/positions/POS1/derived/loss_p95_share_pct"


def test_observe_loss_share_none_for_non_equity_plugin():
    r = result().model_copy(update={"plugin_id": "other"})
    assert observe_loss_share(r, {}) is None


def test_observe_loss_share_none_for_zero_current_value():
    r = result(value_current=0.0)
    assert observe_loss_share(r, {}) is None


def test_observe_pnl_returns_p50_and_metric_path():
    r = result(pnl_p50=-20.0)
    value, path = observe_pnl(r, {})
    assert value == -20.0
    assert path == "/positions/POS1/metrics/equity.pnl/p50"


def test_observe_pnl_none_for_not_completed():
    r = CalculationResult(
        position_id="POS1",
        instrument_id="POS1",
        instrument_type="common_stock",
        plugin_id="equity",
        plugin_version="1.0.0",
        model_id="equity.factor_stress.v1",
        model_version="1.0.0",
        as_of=date(2026, 1, 1),
        horizon=12,
        seed=1,
        execution="not_run",
        status="needs_review",
        scenario_id=SHA,
        flags=["data_missing:price"],
    )
    assert observe_pnl(r, {}) is None


# -- RULES: equity.E1 fires on loss share, equity.E2 is fallback only ------------------------


def _thresholds():
    return {
        rule.rule_id: {
            "metric": rule.observation,
            "operator": rule.operator,
            "threshold": rule.threshold,
            "actions": list(rule.actions),
            "fallback_only": rule.fallback_only,
        }
        for rule in RULES
    }


def test_equity_e1_fires_when_loss_share_crosses_threshold():
    reg = registry()
    r = result(value_current=100.0, loss_p95=30.0)  # 30% >= 20% threshold
    recs = apply(r, reg, _thresholds())
    assert any(rec.rule_id == "equity.E1" for rec in recs)


def test_equity_e2_is_fallback_only_and_does_not_fire_alongside_e1():
    reg = registry()
    # loss share 30% fires E1; pnl p50 is negative too, but E2 is fallback_only so it must not
    # also fire when E1 already did.
    r = result(value_current=100.0, loss_p95=30.0, pnl_p50=-20.0)
    recs = apply(r, reg, _thresholds())
    assert {rec.rule_id for rec in recs} == {"equity.E1"}


def test_equity_e2_fires_alone_when_e1_does_not():
    reg = registry()
    r = result(value_current=100.0, loss_p95=5.0, pnl_p50=-20.0)  # loss share below threshold
    recs = apply(r, reg, _thresholds())
    assert {rec.rule_id for rec in recs} == {"equity.E2"}


# -- tree(): the metric-tree view derived from ShareDetails -----------------------------------


def test_tree_reports_factor_contributions_keyed_by_factor_and_key():
    r = result()
    node = tree(r, {})
    assert node["factors"]["equity.market:MOEX"]["contribution"] == -15.0
    assert node["central"]["pnl"] == -20.0


def test_tree_derives_loss_p95_share_pct():
    r = result(value_current=100.0, loss_p95=30.0)
    node = tree(r, {})
    assert node["derived"]["loss_p95_share_pct"] == 30.0
