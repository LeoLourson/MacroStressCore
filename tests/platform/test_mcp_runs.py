"""msa.mcp.runs pure helpers: summary(), position(), provenance() on hand-built run data.

Covers a portfolio with one completed, one not_run and one excluded-from-the-slice position,
so the helpers' handling of gaps (not just the happy path) is exercised directly, without a
database or an MCP round trip.
"""

from datetime import date

import pytest

from msa.contracts.result import (
    CalculationResult,
    Coverage,
    ExcludedPosition,
    MetricValue,
    PortfolioResult,
    SliceResult,
)
from msa.contracts.risk import Quantiles
from msa.mcp.runs import position, provenance, summary
from msa.platform.registry import build

from .minimal_plugin import MARKET_PLUGIN, PLUGIN_ID, SLICE_ID, VALUE_METRIC, CashModel, plugin

SHA = "a" * 64
REGISTRY = build([plugin, MARKET_PLUGIN])


def completed_result(position_id="POS1"):
    return CalculationResult(
        position_id=position_id,
        instrument_id=position_id,
        instrument_type="minimal_cash",
        plugin_id=PLUGIN_ID,
        plugin_version="1.0.0",
        model_id=CashModel.model_id,
        model_version="1.0.0",
        as_of=date(2026, 1, 1),
        horizon=12,
        seed=1,
        execution="completed",
        status="ok",
        scenario_id=SHA,
        macro_draws_sha256=SHA,
        metrics={
            VALUE_METRIC: MetricValue(
                metric_id=VALUE_METRIC,
                unit="RUB_million",
                quantiles=Quantiles(
                    name=VALUE_METRIC, unit="RUB_million", p05=1.0, p50=2.0, p95=3.0
                ),
            ),
        },
        contributions=[],
    )


def not_run_result(position_id="POS2"):
    return CalculationResult(
        position_id=position_id,
        instrument_id=position_id,
        instrument_type="minimal_cash",
        plugin_id=PLUGIN_ID,
        plugin_version="1.0.0",
        model_id=CashModel.model_id,
        model_version="1.0.0",
        as_of=date(2026, 1, 1),
        horizon=12,
        seed=1,
        execution="not_run",
        status="needs_review",
        scenario_id=SHA,
        flags=["data_missing:fx"],
    )


def portfolio_result():
    slice_result = SliceResult(
        slice_id=SLICE_ID,
        measure="loss",
        unit="RUB_million",
        status="ok",
        loss_quantiles=Quantiles(
            name=SLICE_ID, unit="RUB_million", p05=1.0, p50=2.0, p95=3.0, es95=3.0
        ),
        mean_loss=2.0,
        value_at_risk_95=3.0,
        expected_shortfall_95=3.0,
        coverage=Coverage(basis="market_value", covered_share=1.0, limit=0.05),
        herfindahl=1.0,
        included=["POS1"],
        excluded=[
            ExcludedPosition(position_id="POS3", status="needs_review", reason="data_missing:fx")
        ],
        contributions=[],
    )
    return PortfolioResult(
        run_id="RUN1",
        as_of=date(2026, 1, 1),
        horizon=12,
        seed=1,
        scenario_id=SHA,
        macro_draws_sha256=SHA,
        slices={SLICE_ID: slice_result},
        status="ok",
    )


def run_data(*, with_portfolio=True):
    return {
        "run": {
            "run_id": "RUN1",
            "portfolio_id": "PF1",
            "status": "completed",
            "snapshot_id": "SNAP1",
            "scenario_id": SHA,
            "macro_draws_sha256": SHA,
            "scenario": {"parameters": {}},
            "report": None,
        },
        "payload": {
            "as_of": "2026-01-01",
            "horizon": 12,
            "base_currency": "RUB",
            "position_names": {"POS1": "Позиция один"},
        },
        "results": [completed_result("POS1"), not_run_result("POS2")],
        "portfolio": portfolio_result() if with_portfolio else None,
        "journal": [],
    }


# -- summary() ------------------------------------------------------------------------------


def test_summary_counts_completed_and_not_run_positions():
    out = summary(run_data(), REGISTRY)
    assert out["counts"] == {"positions": 2, "completed": 1, "not_run": 1, "failed": 0}


def test_summary_lists_the_excluded_position_of_the_slice():
    out = summary(run_data(), REGISTRY)
    (slice_out,) = out["slices"]
    assert slice_out["excluded"] == [
        {"position_id": "POS3", "status": "needs_review", "reason": "data_missing:fx"}
    ]


def test_summary_without_a_portfolio_result_has_no_slices():
    out = summary(run_data(with_portfolio=False), REGISTRY)
    assert out["slices"] == []
    assert out["portfolio_status"] is None


def test_summary_position_names_come_from_the_payload():
    out = summary(run_data(), REGISTRY)
    by_id = {p["position_id"]: p for p in out["positions"]}
    assert by_id["POS1"]["name"] == "Позиция один"
    assert by_id["POS2"]["name"] == ""


# -- position() -----------------------------------------------------------------------------


def test_position_of_a_not_run_position_has_no_metrics_and_carries_flags():
    out = position(run_data(), "POS2", REGISTRY)
    assert out["execution"] == "not_run"
    assert out["metrics"] == []
    assert out["flags"][0]["code"] == "data_missing:fx"


def test_position_of_a_completed_position_has_its_metric_with_a_p50_path():
    out = position(run_data(), "POS1", REGISTRY)
    metric = next(m for m in out["metrics"] if m["metric_id"] == VALUE_METRIC)
    assert metric["p50"] == 2.0
    assert metric["path_p50"] == f"/positions/POS1/metrics/{VALUE_METRIC}/p50"


def test_position_unknown_id_raises_keyerror():
    with pytest.raises(KeyError):
        position(run_data(), "NOPE", REGISTRY)


# -- provenance() ---------------------------------------------------------------------------


def test_provenance_of_a_position_metric_includes_model_and_plugin():
    out = provenance(run_data(), f"/positions/POS1/metrics/{VALUE_METRIC}/p50", REGISTRY)
    assert out["value"] == 2.0
    assert out["position_id"] == "POS1"
    assert out["model"] == f"{CashModel.model_id}@1.0.0"
    assert out["plugin"] == f"{PLUGIN_ID}@1.0.0"


def test_provenance_of_a_portfolio_slice_includes_excluded_and_coverage():
    out = provenance(run_data(), f"/portfolio/slices/{SLICE_ID}/loss_quantiles/p50", REGISTRY)
    assert out["value"] == 2.0
    assert out["slice_id"] == SLICE_ID
    assert out["excluded"][0]["position_id"] == "POS3"
    assert out["coverage"]["covered_share"] == 1.0


def test_provenance_of_an_unknown_path_raises_keyerror():
    with pytest.raises(KeyError):
        provenance(run_data(), "/positions/POS1/metrics/nope/p50", REGISTRY)


def test_provenance_not_cited_in_report_when_report_is_absent():
    out = provenance(run_data(), f"/positions/POS1/metrics/{VALUE_METRIC}/p50", REGISTRY)
    assert out["cited_in_report"] is False
    assert "lineage" not in out
