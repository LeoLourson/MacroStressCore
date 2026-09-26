"""msa.engine.snapshot: resolving data requirements against a snapshot as of a date."""

from datetime import date

from msa.contracts.evidence import Evidence, Parameter
from msa.contracts.snapshot import SnapshotItem
from msa.engine.snapshot import DATED_AFTER_AS_OF, MISSING, SnapshotIndex, latest, peers, resolve
from msa.plugin_sdk.model import DataRequirement, DataRequirements

AS_OF = date(2026, 6, 1)


def evidence():
    return Evidence(kind="document", source_id="S", locator="l", fragment_sha256="a" * 64)


def parameter(value=1.0, unit="ratio"):
    return Parameter(value=value, unit=unit, evidence=[evidence()])


def item(item_id, kind="rate", subject="SUBJ", observed_on=AS_OF, **attrs):
    return SnapshotItem(
        item_id=item_id,
        kind=kind,
        subject=subject,
        observed_on=observed_on,
        values={"rate": parameter()},
        attributes=attrs,
    )


def index(*items):
    return SnapshotIndex("SNAP1", items)


def resolve_one(req, idx, *, sector_of=None):
    return resolve(
        DataRequirements(data=[req]),
        idx,
        as_of=AS_OF,
        sector_of=sector_of or (lambda s: None),
    )


def requirement(subject="SUBJ", **overrides):
    values = dict(key="k", kind="rate", subject=subject)
    values.update(overrides)
    return DataRequirement(**values)


# -- latest() ---------------------------------------------------------------------------


def test_latest_picks_item_not_after_as_of():
    idx = index(item("A", observed_on=date(2026, 1, 1)), item("B", observed_on=date(2026, 3, 1)))
    found, reason = latest(idx, requirement(), "SUBJ", AS_OF)
    assert found.item_id == "B"
    assert reason is None


def test_latest_ignores_items_dated_after_as_of():
    idx = index(item("A", observed_on=date(2026, 1, 1)), item("B", observed_on=date(2027, 1, 1)))
    found, reason = latest(idx, requirement(), "SUBJ", AS_OF)
    assert found.item_id == "A"


def test_latest_reports_missing_when_no_candidates():
    idx = index()
    found, reason = latest(idx, requirement(), "SUBJ", AS_OF)
    assert found is None
    assert reason == MISSING


def test_latest_reports_dated_after_as_of_when_only_later_items_exist():
    idx = index(item("A", observed_on=date(2027, 1, 1)))
    found, reason = latest(idx, requirement(), "SUBJ", AS_OF)
    assert found is None
    assert reason == DATED_AFTER_AS_OF


def test_latest_prefer_attribute_breaks_tie_on_same_date():
    idx = index(
        item("RAS", observed_on=AS_OF, standard="RAS"),
        item("IFRS", observed_on=AS_OF, standard="IFRS"),
    )
    req = requirement(prefer_attribute="standard", prefer_order=["IFRS", "RAS"])
    found, _ = latest(idx, req, "SUBJ", AS_OF)
    assert found.item_id == "IFRS"


def test_latest_prefer_order_reversed_changes_the_winner():
    idx = index(
        item("RAS", observed_on=AS_OF, standard="RAS"),
        item("IFRS", observed_on=AS_OF, standard="IFRS"),
    )
    req = requirement(prefer_attribute="standard", prefer_order=["RAS", "IFRS"])
    found, _ = latest(idx, req, "SUBJ", AS_OF)
    assert found.item_id == "RAS"


def test_latest_falls_back_to_item_id_when_attribute_values_tie():
    idx = index(
        item("B", observed_on=AS_OF, standard="RAS"),
        item("A", observed_on=AS_OF, standard="RAS"),
    )
    req = requirement(prefer_attribute="standard", prefer_order=["RAS"])
    found, _ = latest(idx, req, "SUBJ", AS_OF)
    assert found.item_id == "A"


def test_latest_without_prefer_attribute_uses_item_id_as_final_tiebreak():
    idx = index(item("Z", observed_on=AS_OF), item("A", observed_on=AS_OF))
    found, _ = latest(idx, requirement(), "SUBJ", AS_OF)
    assert found.item_id == "A"


# -- resolve() --------------------------------------------------------------------------


def test_resolve_single_subject_requirement():
    idx = index(item("A", observed_on=AS_OF))
    data, missing = resolve(
        DataRequirements(data=[requirement(key="k")]),
        idx,
        as_of=AS_OF,
        sector_of=lambda s: None,
    )
    assert data["k"].item_id == "A"
    assert missing == {}


def test_resolve_records_missing_reason_for_required_and_optional():
    reqs = DataRequirements(
        data=[
            requirement(key="req", subject="NOPE", required=True),
            requirement(key="opt", subject="NOPE", required=False),
        ]
    )
    data, missing = resolve(reqs, index(), as_of=AS_OF, sector_of=lambda s: None)
    assert data["req"] is None
    assert data["opt"] is None
    assert missing == {"req": MISSING, "opt": MISSING}


def test_resolve_many_with_single_subject_returns_a_list():
    idx = index(item("A", observed_on=AS_OF))
    req = DataRequirement(key="k", kind="rate", subject="SUBJ", many=True)
    data, missing = resolve_one(req, idx)
    assert isinstance(data["k"], list)
    assert data["k"][0].item_id == "A"


def test_resolve_many_single_subject_missing_gives_empty_list_and_missing_reason():
    req = DataRequirement(key="k", kind="rate", subject="SUBJ", many=True)
    data, missing = resolve_one(req, index())
    assert data["k"] == []
    assert missing == {"k": MISSING}


def test_resolve_subjects_dedups_and_respects_limit():
    idx = index(
        item("A", subject="X", observed_on=AS_OF),
        item("B", subject="Y", observed_on=AS_OF),
        item("C", subject="Z", observed_on=AS_OF),
    )
    req = DataRequirement(
        key="k",
        kind="rate",
        subjects=["X", "X", "Y", "Z"],
        many=True,
        limit=2,
    )
    data, missing = resolve_one(req, idx)
    assert [i.item_id for i in data["k"]] == ["A", "B"]


def test_resolve_subjects_missing_when_none_resolve():
    req = DataRequirement(key="k", kind="rate", subjects=["X"], many=True)
    data, missing = resolve_one(req, index())
    assert data["k"] == []
    assert missing == {"k": MISSING}


def test_resolve_peers_of_dispatches_to_peers():
    idx = index(item("A", subject="OTHER", observed_on=AS_OF))
    req = DataRequirement(key="k", kind="rate", peers_of="ME", many=True)
    data, _ = resolve(
        DataRequirements(data=[req]),
        idx,
        as_of=AS_OF,
        sector_of=lambda s: {"ME": "23.61", "OTHER": "23.61"}.get(s),
    )
    assert [i.item_id for i in data["k"]] == ["A"]


# -- peers() ------------------------------------------------------------------------------


def test_peers_returns_empty_when_subject_has_no_sector():
    req = DataRequirement(key="k", kind="rate", peers_of="ME", many=True)
    result = peers(index(item("A", subject="OTHER")), req, lambda s: None)
    assert result == []


def test_peers_excludes_the_party_itself():
    idx = index(item("A", subject="ME"), item("B", subject="OTHER"))
    req = DataRequirement(key="k", kind="rate", peers_of="ME", many=True)
    result = peers(idx, req, lambda s: "23.61")
    assert result == ["OTHER"]


def test_peers_only_includes_subjects_with_items_of_the_kind():
    idx = index(item("A", kind="rate", subject="X"), item("B", kind="price", subject="Y"))
    req = DataRequirement(key="k", kind="rate", peers_of="ME", many=True)
    result = peers(idx, req, lambda s: "23.61")
    assert result == ["X"]


def test_peers_ranked_by_deepest_okved_match_first():
    idx = index(item("A", subject="X"), item("B", subject="Y"), item("C", subject="Z"))
    sectors = {"ME": "23.61", "X": "23.60", "Y": "23.61", "Z": "99.99"}
    req = DataRequirement(key="k", kind="rate", peers_of="ME", many=True)
    result = peers(idx, req, sectors.get)
    # Y matches all 4 digits, X matches 3 (23.6), Z matches nothing and is excluded.
    assert result == ["Y", "X"]


def test_peers_excludes_subjects_with_zero_okved_depth():
    idx = index(item("A", subject="X"))
    sectors = {"ME": "23.61", "X": "99.99"}
    req = DataRequirement(key="k", kind="rate", peers_of="ME", many=True)
    result = peers(idx, req, sectors.get)
    assert result == []
