"""msa.contracts.report: Report.approval() — sign-off consistency of a run's report."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from msa.contracts.report import Report

SHA = "a" * 64


def evidence_source(kind="document", **overrides):
    values = {"kind": kind, "source_id": "S", "locator": "l", "fragment_sha256": SHA}
    values.update(overrides)
    return values


def assumption(**overrides):
    values = evidence_source(
        kind="expert_assumption",
        author="analyst",
        as_of="2026-01-01",
    )
    values.update(overrides)
    return values


def report(**overrides):
    values = {
        "run_id": "RUN1",
        "summary": "summary",
        "recommendations": [],
        "assumptions": [],
        "sources": [],
        "numbers": [],
    }
    values.update(overrides)
    return Report(**values)


def test_report_without_approval_is_valid():
    r = report()
    assert r.approved_by is None
    assert r.approved_at is None


def test_report_with_both_approver_and_timestamp_is_valid():
    r = report(
        approved_by="analyst",
        approved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert r.approved_by == "analyst"


def test_report_rejects_approver_without_timestamp():
    with pytest.raises(ValidationError, match="Approval requires both author and timestamp"):
        report(approved_by="analyst")


def test_report_rejects_timestamp_without_approver():
    with pytest.raises(ValidationError, match="Approval requires both author and timestamp"):
        report(approved_at=datetime(2026, 1, 1, tzinfo=UTC))


def test_report_rejects_demo_auto_approval_outside_demo_mode():
    with pytest.raises(ValidationError, match="demo:auto is only allowed in demo reports"):
        report(
            mode="production",
            approved_by="demo:auto",
            approved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_report_accepts_demo_auto_approval_in_demo_mode():
    r = report(
        mode="demo",
        approved_by="demo:auto",
        approved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert r.approved_by == "demo:auto"


def test_report_rejects_non_expert_assumption_evidence():
    with pytest.raises(ValidationError, match="assumptions must contain expert_assumption"):
        report(assumptions=[evidence_source(kind="document")])


def test_report_accepts_expert_assumption_evidence():
    r = report(assumptions=[assumption()])
    assert r.assumptions[0].kind == "expert_assumption"
