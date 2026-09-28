"""Every evidence source_id/author in the demo catalog has words in the registry."""

from demo.catalog import bundle_data, portfolio_ids, snapshot_data, snapshot_ids
from msa.platform.registry import registry


def _evidence_records(obj: object, found: list[dict]) -> None:
    """Recurse through a portfolio/snapshot dict, collecting dicts that look like Evidence."""
    if isinstance(obj, dict):
        if "source_id" in obj and "kind" in obj:
            found.append(obj)
        for value in obj.values():
            _evidence_records(value, found)
    elif isinstance(obj, list):
        for item in obj:
            _evidence_records(item, found)


def _all_evidence() -> list[dict]:
    found: list[dict] = []
    for portfolio_id in portfolio_ids():
        _evidence_records(bundle_data(portfolio_id), found)
    for snapshot_id in snapshot_ids():
        _evidence_records(snapshot_data(snapshot_id), found)
    return found


def test_every_demo_evidence_source_and_author_is_worded():
    evidence = [record for record in _all_evidence() if record["kind"] != "document"]
    source_ids = {record["source_id"] for record in evidence}
    author_ids = {record["author"] for record in evidence if record.get("author")}

    source_wording = registry().source_wording()
    author_wording = registry().author_wording()

    missing_sources = sorted(source_ids - set(source_wording))
    missing_authors = sorted(author_ids - set(author_wording))

    assert not missing_sources and not missing_authors, (
        f"unworded source_id: {missing_sources}; unworded author: {missing_authors}"
    )

    assert source_ids
    assert "demo:companies" in source_ids
    assert "demo:catalog" in author_ids
