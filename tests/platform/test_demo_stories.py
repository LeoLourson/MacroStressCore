"""The business stories must stay complete, reproducible and runnable in the mock profile."""

import json

import pytest

from demo import build_catalog
from demo.catalog import bundle, snapshot
from msa.db.repositories.portfolios import check_bundle
from msa.platform.registry import registry

STORIES = json.loads((build_catalog.CATALOG / "story_catalog.json").read_text("utf-8"))
EVENTS = [
    json.loads(path.read_text("utf-8"))
    for path in sorted((build_catalog.CATALOG / "events").glob("*.json"))
]
STORY_EVENTS = [e for e in EVENTS if e["metadata"]["portfolio_id"] in STORIES["portfolios"]]


@pytest.mark.parametrize("portfolio_id", STORIES["portfolios"])
def test_story_portfolios_validate_with_complete_sourced_snapshots(portfolio_id):
    book = bundle(portfolio_id)
    assert check_bundle(book, registry()) == []
    assert book.portfolio.snapshot_id == STORIES["snapshot_id"]
    assert book.portfolio.metadata["synthetic"] is True
    focus = STORIES["portfolios"][portfolio_id].get("instrument_type")
    if focus:
        assert len(book.positions) >= 4
        assert {i.instrument_type for i in book.instruments} == {focus}
    else:
        assert len(book.positions) == 8
        assert len({i.instrument_type for i in book.instruments}) >= 3
    data = snapshot(book.portfolio.snapshot_id)
    for item in data.items:
        for value in item.values.values():
            assert value.evidence, (item.item_id, value)
            assert all(e.kind == "expert_assumption" for e in value.evidence)


def test_shared_companies_keep_one_identity_and_statement_across_books():
    trade, region, retail = [
        bundle(pid)
        for pid in ("TRADE-CORRIDOR", "REGIONAL-DEVELOPMENT", "EVERYDAY-ECONOMY")
    ]
    data = snapshot(STORIES["snapshot_id"])
    for company, left, right in (
        ("COLD-HUB", trade, region),
        ("MED-SUPPLY", trade, retail),
        ("DIGITAL-SERVICE", region, retail),
    ):
        a = next(p for p in left.parties if p.party_id == company)
        b = next(p for p in right.parties if p.party_id == company)
        assert a == b
        statements = [
            item for item in data.items
            if item.kind == "financial_statement" and item.subject == company
        ]
        assert len(statements) == 1
    legacy = snapshot(build_catalog.SNAPSHOT_ID)
    assert not set(STORIES["companies"]) & {item.subject for item in legacy.items}


def test_every_instrument_type_has_a_homogeneous_portfolio_and_its_own_event():
    focused = {
        pid: header["instrument_type"]
        for pid, header in STORIES["portfolios"].items()
        if "instrument_type" in header
    }
    assert set(focused.values()) == set(registry().instrument_types)
    assert len(focused) == len(registry().instrument_types)
    for portfolio_id in STORIES["portfolios"]:
        assert any(e["metadata"]["portfolio_id"] == portfolio_id for e in STORY_EVENTS)


@pytest.mark.parametrize("event", STORY_EVENTS, ids=lambda e: e["event_id"])
def test_story_expectations_cover_each_position_exactly_once(event):
    positions = {p.position_id for p in bundle(event["metadata"]["portfolio_id"]).positions}
    expected = [pid for group in event["expect"].values() for pid in group]
    assert len(expected) == len(set(expected))
    assert set(expected) == positions
    assert event["metadata"]["synthetic"] is True
    assert len(event["mock_answer"]["scenario"]) >= 3
    if "instrument_type" not in STORIES["portfolios"][event["metadata"]["portfolio_id"]]:
        assert event["expect"]["unaffected"]
        assert len({link["lag"] for link in event["mock_answer"]["links"]}) > 1


@pytest.mark.parametrize("event", EVENTS, ids=lambda e: e["event_id"])
def test_library_event_reaches_report_and_meets_its_economic_expectations(event):
    # Exercise the real workflow, graph validation, model dispatch and report, without LLM/DB.
    # A blocked or failed calculation is a failure even though the sanity CLI exits with 0.
    from sanity.checks import library_check

    verdict = library_check(event)()
    assert verdict.ok is True, verdict.observed
