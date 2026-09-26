"""demo.catalog: portfolios and snapshots assembled from headers and plugin demo_data parts."""

import json

import pytest

from demo.catalog import (
    CatalogError,
    bundle,
    bundle_data,
    parts,
    portfolio_ids,
    snapshot,
    snapshot_data,
)
from demo.pilot import EVENT_ID as PILOT_EVENT_ID
from demo.pilot import seed_pilot
from demo.seed_demo import seed_demo
from msa.cli.plugin import load
from msa.contracts.domain import Portfolio, PortfolioBundle
from msa.db.migrate import migrate
from msa.db.repositories.demo import DemoRepository
from msa.db.session import engine, session_scope
from msa.platform.registry import Registry, installed, registry
from msa.plugin_sdk.plugin import Plugin

PLUGIN_INIT = """\
from msa.plugin_sdk.plugin import Plugin

plugin = Plugin(
    plugin_id={plugin_id!r},
    version="1.0.0",
    sdk=">=1.0,<2.0",
    label={plugin_id!r},
)
"""


def _write_plugin(tmp_path, plugin_id, *, portfolios=None, snapshots=None):
    """A temporary plugin package named ``plugin_id`` with demo_data parts, via ``load()``."""
    package = tmp_path / plugin_id
    package.mkdir()
    (package / "__init__.py").write_text(PLUGIN_INIT.format(plugin_id=plugin_id), encoding="utf-8")
    for kind, parts_by_id in (("portfolios", portfolios), ("snapshots", snapshots)):
        if not parts_by_id:
            continue
        folder = package / "demo_data" / kind
        folder.mkdir(parents=True)
        for stem, data in parts_by_id.items():
            (folder / f"{stem}.json").write_text(json.dumps(data), encoding="utf-8")
    return load(package)


@pytest.fixture
def root(tmp_path):
    """A temporary demo root with a core header for portfolio X-1 and snapshot S-1."""
    demo_root = tmp_path / "demo"
    (demo_root / "portfolios").mkdir(parents=True)
    (demo_root / "snapshots").mkdir(parents=True)
    (demo_root / "portfolios" / "X-1.json").write_text(
        json.dumps({"portfolio": {"portfolio_id": "X-1", "name": "X-1"}}), encoding="utf-8"
    )
    (demo_root / "snapshots" / "S-1.json").write_text(
        json.dumps({"snapshot_id": "S-1", "as_of": "2026-01-01", "label": "S-1"}),
        encoding="utf-8",
    )
    return demo_root


# -- the real catalog ---------------------------------------------------------------------


def test_portfolio_ids_include_the_demo_portfolios():
    assert {"MULTI-ASSET", "ATYPICAL-BORROWERS", "LOAD-TEST"} <= set(portfolio_ids())


def test_demo1_bundle_position_order_is_credit_then_equity():
    positions = bundle("MULTI-ASSET").positions
    assert [p.position_id for p in positions] == [
        "BOND-CONCRETE",
        "PROJECT-HOUSING",
        "LOAN-MACHINERY",
        "LOAN-LEASING",
        "LOAN-FERTILIZER",
        "SHARE-OIL",
        "SHARE-US-TECH",
    ]


def test_demo2_and_demo3_bundles_validate():
    assert bundle("ATYPICAL-BORROWERS").portfolio.portfolio_id == "ATYPICAL-BORROWERS"
    assert bundle("LOAD-TEST").portfolio.portfolio_id == "LOAD-TEST"


def test_demo1_instrument_issuers_are_among_its_parties():
    b = bundle("MULTI-ASSET")
    party_ids = {p.party_id for p in b.parties}
    for instrument in b.instruments:
        assert instrument.issuer_id in party_ids


def test_snapshot_items_are_sorted_and_cover_credit_and_equity_kinds():
    items = snapshot("SYNTHETIC-2026-09-11").items
    ids = [item.item_id for item in items]
    assert ids == sorted(ids)
    kinds = {item.kind for item in items}
    assert {"financial_statement", "rate"} <= kinds
    assert {"price", "fx_rate", "sensitivity", "dividend"} <= kinds


# -- merging plugin parts -------------------------------------------------------------------


def test_plugin_parts_merge_in_registry_order(tmp_path, root):
    shared = {"party_id": "P-SHARED", "name": "Shared Co", "kind": "company"}
    catone = _write_plugin(
        tmp_path,
        "catone",
        portfolios={
            "X-1": {
                "parties": [shared, {"party_id": "P-ONE", "name": "One Co", "kind": "company"}],
                "instruments": [],
                "positions": [],
            }
        },
    )
    cattwo = _write_plugin(
        tmp_path,
        "cattwo",
        portfolios={
            "X-1": {
                "parties": [shared, {"party_id": "P-TWO", "name": "Two Co", "kind": "company"}],
                "instruments": [],
                "positions": [],
            }
        },
    )
    with installed(catone, cattwo) as reg:
        # Do not assume argument order survives into the registry: read it back.
        order = [pid for pid in reg.plugins if pid in {"catone", "cattwo"}]
        assert order == ["catone", "cattwo"]
        data = bundle_data("X-1", registry=reg, root=root)
    assert [p["party_id"] for p in data["parties"]] == ["P-SHARED", "P-ONE", "P-TWO"]


def test_identical_record_from_two_plugins_is_kept_once(tmp_path, root):
    shared = {"party_id": "P-SHARED", "name": "Shared Co", "kind": "company"}
    catone = _write_plugin(
        tmp_path,
        "catone",
        portfolios={"X-1": {"parties": [shared], "instruments": [], "positions": []}},
    )
    cattwo = _write_plugin(
        tmp_path,
        "cattwo",
        portfolios={"X-1": {"parties": [shared], "instruments": [], "positions": []}},
    )
    with installed(catone, cattwo) as reg:
        data = bundle_data("X-1", registry=reg, root=root)
    assert [p["party_id"] for p in data["parties"]] == ["P-SHARED"]


def test_conflicting_record_from_two_plugins_raises_naming_the_id(tmp_path, root):
    catone = _write_plugin(
        tmp_path,
        "catone",
        portfolios={
            "X-1": {
                "parties": [{"party_id": "P-CONFLICT", "name": "A version", "kind": "company"}],
                "instruments": [],
                "positions": [],
            }
        },
    )
    cattwo = _write_plugin(
        tmp_path,
        "cattwo",
        portfolios={
            "X-1": {
                "parties": [{"party_id": "P-CONFLICT", "name": "B version", "kind": "company"}],
                "instruments": [],
                "positions": [],
            }
        },
    )
    with installed(catone, cattwo) as reg:
        with pytest.raises(CatalogError, match="P-CONFLICT"):
            bundle_data("X-1", registry=reg, root=root)


def test_snapshot_items_merge_from_two_plugins_and_sort(tmp_path, root):
    catone = _write_plugin(
        tmp_path,
        "catone",
        snapshots={
            "S-1": {
                "items": [
                    {
                        "item_id": "b-item",
                        "kind": "price",
                        "subject": "X",
                        "observed_on": "2026-01-01",
                        "values": {},
                    }
                ]
            }
        },
    )
    cattwo = _write_plugin(
        tmp_path,
        "cattwo",
        snapshots={
            "S-1": {
                "items": [
                    {
                        "item_id": "a-item",
                        "kind": "price",
                        "subject": "Y",
                        "observed_on": "2026-01-01",
                        "values": {},
                    }
                ]
            }
        },
    )
    with installed(catone, cattwo) as reg:
        data = snapshot_data("S-1", registry=reg, root=root)
    assert [item["item_id"] for item in data["items"]] == ["a-item", "b-item"]


# -- a plugin's own portfolio/snapshot header ------------------------------------------------


def test_plugin_header_adds_a_portfolio_the_core_does_not_have(tmp_path, root):
    catown = _write_plugin(
        tmp_path,
        "catown",
        portfolios={
            "Y-1": {
                "portfolio": {"portfolio_id": "Y-1", "name": "Y-1"},
                "parties": [],
                "instruments": [],
                "positions": [],
            }
        },
    )
    with installed(catown) as reg:
        ids = portfolio_ids(reg, root=root)
    assert ids == ["X-1", "Y-1"]


def test_two_headers_of_one_portfolio_raise_catalog_error(tmp_path, root):
    catdup = _write_plugin(
        tmp_path,
        "catdup",
        portfolios={"X-1": {"portfolio": {"portfolio_id": "X-1", "name": "X-1 from plugin"}}},
    )
    with installed(catdup) as reg:
        with pytest.raises(CatalogError, match="X-1"):
            portfolio_ids(reg, root=root)


# -- a code-only plugin has no demo data ------------------------------------------------------


def test_parts_skips_a_plugin_declared_without_a_package():
    nopkg = Plugin(plugin_id="nopkg", version="1.0.0", sdk=">=1.0,<2.0", label="No package")
    reg = Registry(plugins={"nopkg": nopkg})
    assert parts("portfolios", reg) == []


# -- seeding a fresh database -------------------------------------------------------------


def test_seed_demo_counts_positions_and_snapshot_items(tmp_path):
    bind = engine(f"sqlite:///{tmp_path / 'msa.db'}")
    try:
        migrate(bind)
        counts = seed_demo(bind)
    finally:
        bind.dispose()
    assert counts["MULTI-ASSET"] == 7
    assert counts["SYNTHETIC-2026-09-11"] == 71


def test_reseeding_retires_stale_builtin_portfolios_and_events_but_keeps_the_pilot(tmp_path):
    bind = engine(f"sqlite:///{tmp_path / 'msa.db'}")
    try:
        migrate(bind)
        seed_demo(bind)
        seed_pilot(bind)
        with session_scope(bind, scope="demo", scopes={"demo:*"}) as session:
            repository = DemoRepository(session)
            repository.seed_portfolio(
                PortfolioBundle(portfolio=Portfolio(portfolio_id="STALE-PORTFOLIO", name="S")),
                registry=registry(),
            )
            repository.seed_event(
                {"event_id": "STALE-EVENT", "title": "t", "text": "t", "metadata": {}}
            )
        seed_demo(bind)
        with session_scope(bind, scope="demo", scopes={"demo:*"}) as session:
            repository = DemoRepository(session)
            portfolios = repository.portfolios.list_portfolios()
            portfolio_ids_after = {row["portfolio_id"] for row in portfolios}
            event_ids_after = {row["event_id"] for row in repository.events()}
    finally:
        bind.dispose()
    assert {"MULTI-ASSET", "ATYPICAL-BORROWERS", "LOAD-TEST"} <= portfolio_ids_after
    assert "STALE-PORTFOLIO" not in portfolio_ids_after
    assert {"RECYCLING-FEE", "MORTGAGE-DOWN-PAYMENT", PILOT_EVENT_ID} <= event_ids_after
    assert "STALE-EVENT" not in event_ids_after
