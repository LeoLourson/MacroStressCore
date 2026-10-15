"""msa.plugin_sdk.model: DataRequirement selectors, PreparedInputs lookups, Diagnostics.blocking."""

from datetime import date

import pytest
from pydantic import ValidationError

from msa.contracts.domain import Instrument, Position, PositionContext
from msa.contracts.snapshot import SnapshotItem
from msa.plugin_sdk.model import DataRequirement, Diagnostic, Diagnostics, PreparedInputs

# -- DataRequirement.one_selector -----------------------------------------------------


def test_requirement_with_subject_only_is_valid():
    r = DataRequirement(key="k", kind="rate", subject="S1")
    assert r.subject == "S1"


def test_requirement_with_subjects_and_many_is_valid():
    r = DataRequirement(key="k", kind="rate", subjects=["A", "B"], many=True)
    assert r.subjects == ["A", "B"]


def test_requirement_with_peers_of_and_many_is_valid():
    r = DataRequirement(key="k", kind="rate", peers_of="P1", many=True)
    assert r.peers_of == "P1"


def test_requirement_with_no_selector_is_rejected():
    with pytest.raises(ValidationError, match="exactly one of subject, subjects, peers_of"):
        DataRequirement(key="k", kind="rate")


def test_requirement_with_two_selectors_is_rejected():
    with pytest.raises(ValidationError, match="exactly one of subject, subjects, peers_of"):
        DataRequirement(key="k", kind="rate", subject="S1", subjects=["A"], many=True)


def test_requirement_with_subject_and_peers_of_is_rejected():
    with pytest.raises(ValidationError, match="exactly one of subject, subjects, peers_of"):
        DataRequirement(key="k", kind="rate", subject="S1", peers_of="P1", many=True)


def test_requirement_subjects_without_many_is_rejected():
    with pytest.raises(ValidationError, match="select many items"):
        DataRequirement(key="k", kind="rate", subjects=["A"], many=False)


def test_requirement_peers_of_without_many_is_rejected():
    with pytest.raises(ValidationError, match="select many items"):
        DataRequirement(key="k", kind="rate", peers_of="P1", many=False)


def test_requirement_subject_with_many_true_is_allowed():
    # `many` is only mandatory for subjects/peers_of, not forbidden for `subject`.
    r = DataRequirement(key="k", kind="rate", subject="S1", many=True)
    assert r.many


# -- PreparedInputs.item / items -------------------------------------------------------


def snapshot_item(item_id="ITEM1"):
    return SnapshotItem(
        item_id=item_id,
        kind="rate",
        subject="SUBJ",
        observed_on=date(2026, 1, 1),
    )


def position_context():
    instrument = Instrument(instrument_id="I1", instrument_type="minimal_cash", name="I1")
    return PositionContext(
        portfolio_id="PF1",
        position=Position(position_id="POS1", instrument_id="I1"),
        instrument=instrument,
        issuer=None,
    )


def prepared(data):
    return PreparedInputs(
        context=position_context(),
        model_id="minimal.cash.v1",
        as_of=date(2026, 1, 1),
        horizon=12,
        snapshot_id="SNAP1",
        data=data,
    )


def test_item_returns_single_resolved_value():
    single = snapshot_item()
    p = prepared({"k": single})
    # Contract revalidates instances on assignment, so compare by value, not identity.
    assert p.item("k") == single


def test_item_returns_none_when_absent():
    p = prepared({})
    assert p.item("missing") is None


def test_item_raises_type_error_when_key_resolves_to_a_list():
    p = prepared({"k": [snapshot_item("A"), snapshot_item("B")]})
    with pytest.raises(TypeError, match="resolves to several items"):
        p.item("k")


def test_items_returns_list_as_is():
    a, b = snapshot_item("A"), snapshot_item("B")
    p = prepared({"k": [a, b]})
    assert [i.item_id for i in p.items("k")] == ["A", "B"]


def test_items_wraps_a_single_value_in_a_list():
    single = snapshot_item()
    p = prepared({"k": single})
    assert p.items("k") == [single]


def test_items_returns_empty_list_when_none_or_absent():
    p = prepared({"k": None})
    assert p.items("k") == []
    assert p.items("missing") == []


# -- Diagnostics.blocking --------------------------------------------------------------


def test_blocking_returns_only_error_severity_items():
    diagnostics = Diagnostics(
        items=[
            Diagnostic(code="a", severity="error"),
            Diagnostic(code="b", severity="warning"),
            Diagnostic(code="c", severity="info"),
            Diagnostic(code="d", severity="error"),
        ]
    )
    assert [d.code for d in diagnostics.blocking] == ["a", "d"]


def test_blocking_is_empty_without_errors():
    diagnostics = Diagnostics(items=[Diagnostic(code="a", severity="warning")])
    assert diagnostics.blocking == []


def test_blocking_is_empty_without_items():
    assert Diagnostics().blocking == []
