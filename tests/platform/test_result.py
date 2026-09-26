"""msa.contracts.result: MetricValue, CalculationResult, contributions, slices, portfolio."""

from datetime import date

import pytest
from pydantic import ValidationError

from msa.contracts.result import (
    AggregationContribution,
    CalculationResult,
    Coverage,
    Diagnostic,
    ExcludedPosition,
    MetricValue,
    PortfolioResult,
    PositionContribution,
    SliceResult,
)
from msa.contracts.risk import Quantiles

SHA = "a" * 64


def quantiles(name="m", unit="fraction", p05=1.0, p50=2.0, p95=3.0, es95=None):
    return Quantiles(name=name, unit=unit, p05=p05, p50=p50, p95=p95, es95=es95)


# -- MetricValue --------------------------------------------------------------------


def test_metric_value_with_only_a_value_is_valid():
    m = MetricValue(metric_id="m", unit="fraction", value=1.0)
    assert m.quantiles is None


def test_metric_value_with_only_quantiles_is_valid():
    m = MetricValue(metric_id="m", unit="fraction", quantiles=quantiles())
    assert m.value is None


def test_metric_value_requires_value_or_quantiles():
    with pytest.raises(ValidationError, match="neither a value nor quantiles"):
        MetricValue(metric_id="m", unit="fraction")


def test_metric_value_quantiles_unit_must_match():
    with pytest.raises(ValidationError, match="another unit"):
        MetricValue(metric_id="m", unit="fraction", quantiles=quantiles(unit="ratio"))


# -- AggregationContribution ---------------------------------------------------------


def contribution(admission="included", draws=(1.0, 2.0), **overrides):
    values = {
        "slice_id": "market.pnl",
        "measure": "loss",
        "unit": "RUB_million",
        "horizon": 12,
        "scenario_id": SHA,
        "exposure": 10.0,
        "exposure_basis": "market_value",
        "admission": admission,
        "draws": list(draws) if draws is not None else None,
    }
    values.update(overrides)
    return AggregationContribution(**values)


def test_contribution_included_enters():
    assert contribution(admission="included").enters


def test_contribution_admitted_enters():
    assert contribution(admission="admitted:rule1").enters


def test_contribution_excluded_does_not_enter():
    assert not contribution(admission="excluded:reason", draws=None).enters


def test_contribution_draws_excluded_from_model_dump():
    c = contribution()
    dumped = c.model_dump(mode="json")
    assert "draws" not in dumped
    assert c.draws == [1.0, 2.0]


# -- CalculationResult ----------------------------------------------------------------


def result(**overrides):
    values = dict(
        position_id="POS1",
        instrument_id="I1",
        instrument_type="minimal_cash",
        plugin_id="minimal",
        plugin_version="1.0.0",
        model_id="minimal.cash.v1",
        model_version="1.0.0",
        as_of=date(2026, 1, 1),
        horizon=12,
        seed=1,
        execution="completed",
        status="ok",
        scenario_id=SHA,
    )
    values.update(overrides)
    return CalculationResult(**values)


def test_completed_ok_result_is_valid():
    r = result()
    assert r.status == "ok"


def test_metric_key_must_match_its_id():
    with pytest.raises(ValidationError, match="differs from its id"):
        result(metrics={"wrong_key": MetricValue(metric_id="right", unit="fraction", value=1.0)})


def test_not_completed_result_reports_no_metrics():
    with pytest.raises(ValidationError, match="reports no numbers"):
        result(
            execution="not_run",
            status="needs_review",
            flags=["f"],
            metrics={"m": MetricValue(metric_id="m", unit="fraction", value=1.0)},
        )


def test_not_completed_result_reports_no_contributions():
    with pytest.raises(ValidationError, match="reports no numbers"):
        result(
            execution="not_run",
            status="needs_review",
            flags=["f"],
            contributions=[contribution()],
        )


def test_not_completed_result_cannot_be_ok():
    with pytest.raises(ValidationError, match="cannot be ok"):
        result(execution="not_run", status="ok")


@pytest.mark.parametrize("status", ["needs_review", "incomplete", "invalid"])
def test_review_statuses_require_a_flag_or_error_diagnostic(status):
    with pytest.raises(ValidationError, match="requires a reason"):
        result(status=status)


@pytest.mark.parametrize("status", ["needs_review", "incomplete", "invalid"])
def test_review_statuses_accepted_with_a_flag(status):
    r = result(status=status, flags=["some_flag"])
    assert r.status == status


@pytest.mark.parametrize("status", ["needs_review", "incomplete", "invalid"])
def test_review_statuses_accepted_with_an_error_diagnostic(status):
    r = result(
        status=status,
        diagnostics=[Diagnostic(code="c", severity="error")],
    )
    assert r.status == status


def test_review_status_not_satisfied_by_warning_diagnostic_alone():
    with pytest.raises(ValidationError, match="requires a reason"):
        result(status="needs_review", diagnostics=[Diagnostic(code="c", severity="warning")])


def test_result_contributes_to_each_slice_at_most_once():
    with pytest.raises(ValidationError, match="at most once"):
        result(
            contributions=[
                contribution(slice_id="market.pnl"),
                contribution(slice_id="market.pnl"),
            ]
        )


def test_contribution_horizon_must_match_result_horizon():
    with pytest.raises(ValidationError, match="must share the result's horizon"):
        result(horizon=12, contributions=[contribution(horizon=6)])


def test_contribution_scenario_must_match_result_scenario():
    with pytest.raises(ValidationError, match="must share the result's horizon and scenario"):
        result(scenario_id=SHA, contributions=[contribution(scenario_id="b" * 64)])


def test_result_allows_several_distinct_slices():
    r = result(
        contributions=[
            contribution(slice_id="market.pnl"),
            contribution(slice_id="credit.loss"),
        ]
    )
    assert len(r.contributions) == 2


# -- SliceResult: completeness_is_explicit -------------------------------------------


def coverage(covered_share=1.0, limit=0.05, unknown_exposure=()):
    return Coverage(
        basis="market_value",
        covered_share=covered_share,
        limit=limit,
        unknown_exposure=list(unknown_exposure),
    )


def slice_result(**overrides):
    values = dict(
        slice_id="market.pnl",
        measure="loss",
        unit="RUB_million",
        status="ok",
        coverage=coverage(),
        herfindahl=0.5,
    )
    values.update(overrides)
    return SliceResult(**values)


def test_empty_slice_is_valid():
    s = slice_result()
    assert s.loss_quantiles is None
    assert s.included == []


def test_slice_with_included_requires_loss_quantiles():
    with pytest.raises(ValidationError, match="require slice loss quantiles"):
        slice_result(included=["POS1"])


def test_slice_quantiles_require_at_least_one_included_position():
    with pytest.raises(ValidationError, match="require at least one included position"):
        slice_result(loss_quantiles=quantiles(unit="RUB_million", es95=3.0))


def test_empty_slice_must_not_report_loss_statistics():
    with pytest.raises(ValidationError, match="empty slice must not report"):
        slice_result(mean_loss=1.0)


def test_slice_quantiles_must_be_in_slice_unit():
    with pytest.raises(ValidationError, match="must be in the slice unit"):
        slice_result(
            included=["POS1"],
            loss_quantiles=quantiles(unit="fraction", es95=3.0),
            mean_loss=1.0,
            expected_shortfall_95=3.0,
        )


def test_slice_quantiles_es95_must_match_expected_shortfall():
    with pytest.raises(ValidationError, match="ES95 must match"):
        slice_result(
            included=["POS1"],
            loss_quantiles=quantiles(unit="RUB_million", es95=3.0),
            mean_loss=1.0,
            expected_shortfall_95=99.0,
        )


def test_slice_below_coverage_limit_requires_incomplete_status():
    with pytest.raises(ValidationError, match="requires incomplete status"):
        slice_result(
            status="ok",
            coverage=coverage(covered_share=0.5, limit=0.05),
            included=["POS1"],
            loss_quantiles=quantiles(unit="RUB_million", es95=3.0),
            mean_loss=1.0,
            expected_shortfall_95=3.0,
            flags=["gap"],
        )


def test_slice_below_coverage_limit_is_valid_as_incomplete():
    s = slice_result(
        status="incomplete",
        coverage=coverage(covered_share=0.5, limit=0.05),
        included=["POS1"],
        loss_quantiles=quantiles(unit="RUB_million", es95=3.0),
        mean_loss=1.0,
        expected_shortfall_95=3.0,
        flags=["gap"],
    )
    assert s.status == "incomplete"


def test_slice_with_unknown_exposure_requires_incomplete_status():
    with pytest.raises(ValidationError, match="requires incomplete status"):
        slice_result(status="ok", coverage=coverage(unknown_exposure=["POS9"]))


@pytest.mark.parametrize("status", ["needs_review", "incomplete", "invalid"])
def test_review_slice_status_requires_flags(status):
    with pytest.raises(ValidationError, match="requires a reason"):
        slice_result(status=status, coverage=coverage(covered_share=1.0, unknown_exposure=[]))


def test_position_cannot_be_both_included_and_excluded():
    with pytest.raises(ValidationError, match="cannot be both included and excluded"):
        slice_result(
            included=["POS1"],
            excluded=[ExcludedPosition(position_id="POS1", status="invalid", reason="r")],
            loss_quantiles=quantiles(unit="RUB_million", es95=3.0),
            mean_loss=1.0,
            expected_shortfall_95=3.0,
        )


def test_slice_with_position_contributions_is_valid():
    s = slice_result(
        included=["POS1"],
        loss_quantiles=quantiles(unit="RUB_million", es95=3.0),
        mean_loss=1.0,
        expected_shortfall_95=3.0,
        contributions=[
            PositionContribution(
                position_id="POS1",
                mean_loss=1.0,
                expected_shortfall_contribution=1.0,
                p95_standalone=1.0,
            )
        ],
    )
    assert s.contributions[0].position_id == "POS1"


# -- PortfolioResult: keyed -----------------------------------------------------------


def portfolio_result(**overrides):
    values = dict(
        run_id="RUN1",
        as_of=date(2026, 1, 1),
        horizon=12,
        seed=1,
        scenario_id=SHA,
        macro_draws_sha256=SHA,
        status="ok",
    )
    values.update(overrides)
    return PortfolioResult(**values)


def test_portfolio_result_with_no_slices_is_valid():
    p = portfolio_result()
    assert p.slices == {}


def test_portfolio_slice_key_must_match_its_id():
    with pytest.raises(ValidationError, match="differs from its id"):
        portfolio_result(slices={"wrong": slice_result(slice_id="market.pnl")})


@pytest.mark.parametrize("status", ["needs_review", "incomplete", "invalid"])
def test_portfolio_review_status_requires_a_flag_somewhere(status):
    with pytest.raises(ValidationError, match="requires a reason"):
        portfolio_result(status=status)


def test_portfolio_review_status_satisfied_by_own_flags():
    p = portfolio_result(status="needs_review", flags=["some_flag"])
    assert p.status == "needs_review"


def test_portfolio_review_status_satisfied_by_slice_flags():
    p = portfolio_result(
        status="needs_review",
        slices={
            "market.pnl": slice_result(
                slice_id="market.pnl",
                status="needs_review",
                coverage=coverage(covered_share=1.0),
                flags=["slice_flag"],
            )
        },
    )
    assert p.status == "needs_review"
