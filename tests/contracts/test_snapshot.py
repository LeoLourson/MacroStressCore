"""msa.contracts.snapshot: DataSnapshot uniqueness, dating and content hash."""

from datetime import date

import pytest
from pydantic import ValidationError

from msa.contracts.evidence import Evidence, Parameter
from msa.contracts.snapshot import DataSnapshot, SnapshotItem, content_hash


def evidence():
    return Evidence(
        kind="document",
        source_id="S1",
        locator="loc",
        fragment_sha256="a" * 64,
    )


def parameter(value=1.0, unit="ratio"):
    return Parameter(value=value, unit=unit, evidence=[evidence()])


def item(item_id="ITEM1", observed_on=date(2026, 1, 1), **overrides):
    values = {
        "item_id": item_id,
        "kind": "rate",
        "subject": "SUBJ",
        "observed_on": observed_on,
        "values": {"rate": parameter()},
    }
    values.update(overrides)
    return SnapshotItem(**values)


def snapshot(items=None, as_of=date(2026, 6, 1), **overrides):
    values = {
        "snapshot_id": "SNAP1",
        "as_of": as_of,
        "label": "label",
        "items": items or [],
    }
    values.update(overrides)
    return DataSnapshot(**values)


def test_snapshot_accepts_items_dated_on_or_before_as_of():
    snap = snapshot([item(observed_on=date(2026, 6, 1))], as_of=date(2026, 6, 1))
    assert len(snap.items) == 1


def test_snapshot_rejects_duplicate_item_ids():
    with pytest.raises(ValidationError, match="item ids must be unique"):
        snapshot([item("A"), item("A")])


def test_snapshot_rejects_items_dated_after_as_of():
    with pytest.raises(ValidationError, match="dated after"):
        snapshot([item("A", observed_on=date(2026, 7, 1))], as_of=date(2026, 6, 1))


def test_snapshot_sha256_property_matches_content_hash():
    snap = snapshot([item("A")])
    assert snap.sha256 == content_hash(snap)


def test_content_hash_is_independent_of_item_order():
    a = snapshot([item("A", observed_on=date(2026, 1, 1)), item("B", observed_on=date(2026, 1, 2))])
    b = snapshot([item("B", observed_on=date(2026, 1, 2)), item("A", observed_on=date(2026, 1, 1))])
    assert content_hash(a) == content_hash(b)


def test_content_hash_is_independent_of_metadata():
    a = snapshot([item("A")], metadata={"note": "x"})
    b = snapshot([item("A")], metadata={"note": "y", "extra": 1})
    assert content_hash(a) == content_hash(b)


def test_content_hash_differs_when_items_differ():
    a = snapshot([item("A")])
    b = snapshot([item("A", observed_on=date(2026, 2, 1))])
    assert content_hash(a) != content_hash(b)


def test_content_hash_differs_when_as_of_differs():
    a = snapshot([item("A")], as_of=date(2026, 6, 1))
    b = snapshot([item("A")], as_of=date(2026, 12, 1))
    assert content_hash(a) != content_hash(b)
