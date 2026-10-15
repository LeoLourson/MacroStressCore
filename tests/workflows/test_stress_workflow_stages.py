"""msa.workflows.stress_test: writing the report is a stage between portfolio and decision."""

from msa.workflows.stress_test import STRESS_TEST


def stage(stage_id):
    return next(item for item in STRESS_TEST.stages if item.stage_id == stage_id)


def test_stage_order():
    assert [item.stage_id for item in STRESS_TEST.stages] == [
        "event",
        "scenario",
        "calculation",
        "portfolio",
        "report",
        "decision",
    ]


def test_portfolio_stage_holds_the_aggregate_and_after_calculation():
    assert stage("portfolio").nodes == ("aggregate", "after_calculation")


def test_report_stage_holds_the_advisory_agent():
    assert stage("report").nodes == ("advisory_agent",)
    assert STRESS_TEST.node("advisory_agent").stage == "report"
