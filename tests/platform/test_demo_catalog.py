"""demo.catalog: portfolios and snapshots assembled from headers and plugin demo_data parts."""

import json

import pytest

from demo import build_catalog
from demo.catalog import (
    CatalogError,
    bundle,
    bundle_data,
    collection_of,
    collections,
    event_paths,
    parts,
    portfolio_ids,
    snapshot,
    snapshot_data,
    snapshot_ids,
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
        folder = package / "demo_data" / "synthetic" / kind
        folder.mkdir(parents=True)
        for stem, data in parts_by_id.items():
            (folder / f"{stem}.json").write_text(json.dumps(data), encoding="utf-8")
    return load(package)


@pytest.fixture
def root(tmp_path):
    """A temporary demo root with a synthetic header for portfolio X-1 and snapshot S-1."""
    demo_root = tmp_path / "demo"
    (demo_root / "synthetic" / "portfolios").mkdir(parents=True)
    (demo_root / "synthetic" / "snapshots").mkdir(parents=True)
    (demo_root / "synthetic" / "portfolios" / "X-1.json").write_text(
        json.dumps({"portfolio": {"portfolio_id": "X-1", "name": "X-1"}}), encoding="utf-8"
    )
    (demo_root / "synthetic" / "snapshots" / "S-1.json").write_text(
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


def test_every_item_says_whether_it_is_synthetic_as_its_collection_does():
    assert collections(build_catalog.CATALOG)[0] == "synthetic"
    assert {"historical/etalon", "historical/afk-systema"} <= set(
        collections(build_catalog.CATALOG)
    )
    for path in event_paths():
        collection = path.parent.parent.relative_to(build_catalog.CATALOG).as_posix()
        synthetic = json.loads(path.read_text("utf-8"))["metadata"]["synthetic"]
        assert synthetic is (collection == "synthetic"), path
    for portfolio_id in portfolio_ids():
        synthetic = bundle(portfolio_id).portfolio.metadata["synthetic"]
        assert synthetic is (collection_of("portfolios", portfolio_id) == "synthetic")
    for snapshot_id in snapshot_ids():
        synthetic = snapshot(snapshot_id).metadata["synthetic"]
        assert synthetic is (collection_of("snapshots", snapshot_id) == "synthetic")


def test_a_header_contradicting_its_collection_raises(root):
    case = root / "historical" / "case" / "portfolios"
    case.mkdir(parents=True)
    (case / "H-1.json").write_text(
        json.dumps(
            {"portfolio": {"portfolio_id": "H-1", "name": "H", "metadata": {"synthetic": True}}}
        ),
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="H-1"):
        portfolio_ids(root=root)


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


# -- the generated part of the catalog --------------------------------------------------------


def test_the_generated_catalog_files_match_the_generator():
    stale = [
        str(path)
        for path, text in build_catalog.outputs().items()
        if not path.exists() or path.read_text("utf-8") != text
    ]
    assert stale == [], "run: uv run --frozen python -m demo.build_catalog"


def test_every_library_event_names_a_catalog_portfolio_and_what_must_follow():
    events = event_paths()
    assert events
    for path in events:
        event = json.loads(path.read_text("utf-8"))
        assert event["event_id"] == path.stem
        assert event["metadata"]["portfolio_id"] in portfolio_ids()
        positions = {p.position_id for p in bundle(event["metadata"]["portfolio_id"]).positions}
        named = {pid for ids in event["expect"].values() for pid in ids}
        assert named <= positions, path.stem


# -- a portfolio with a snapshot of its own ------------------------------------------------

OIL_SNAPSHOT = "SYNTHETIC-OIL-CREDIT-2026-09-11"
SGZH_SNAPSHOT = "SYNTHETIC-SGZH-2026-09-11"


def test_oil_credit_holds_one_corporate_loan_on_its_own_snapshot():
    oil = bundle("OIL-CREDIT")
    assert [p.position_id for p in oil.positions] == ["LOAN-OIL-MAJOR"]
    assert [i.instrument_type for i in oil.instruments] == ["corp_loan"]
    assert oil.portfolio.snapshot_id == OIL_SNAPSHOT == build_catalog.OWN_SNAPSHOTS["OIL-CREDIT"][0]


def test_the_seeded_themed_snapshot_does_not_gain_the_oil_company():
    # A seeded snapshot never changes: the company of a later portfolio goes to its own.
    themed = snapshot(build_catalog.SNAPSHOT_ID)
    assert not [item for item in themed.items if item.subject == "OIL-MAJOR"]
    statements = [
        item
        for item in snapshot(OIL_SNAPSHOT).items
        if item.subject == "OIL-MAJOR" and item.kind == "financial_statement"
    ]
    assert len(statements) == 1
    assert statements[0].values["capex"].value > 0


def test_each_snapshot_gets_a_header_with_its_label():
    headers = {
        path.stem: json.loads(text)
        for path, text in build_catalog.outputs().items()
        if path.parent == build_catalog.SYNTHETIC / "snapshots"
    }
    labels = {build_catalog.SNAPSHOT_ID: build_catalog.SNAPSHOT_LABEL} | dict(
        build_catalog.OWN_SNAPSHOTS.values()
    )
    stories = json.loads((build_catalog.SYNTHETIC / "story_catalog.json").read_text("utf-8"))
    labels[stories["snapshot_id"]] = stories["snapshot_label"]
    assert {sid: header["label"] for sid, header in headers.items()} == labels


def test_seeding_the_same_database_twice_keeps_the_own_snapshot(tmp_path):
    bind = engine(f"sqlite:///{tmp_path / 'msa.db'}")
    try:
        migrate(bind)
        seed_demo(bind)
        counts = seed_demo(bind)
    finally:
        bind.dispose()
    assert counts["OIL-CREDIT"] == 1
    assert counts[OIL_SNAPSHOT] > 0
    assert counts["SGZH-CREDIT"] == 1
    assert counts[SGZH_SNAPSHOT] > 0
    assert counts["TRADE-CORRIDOR"] == 8
    assert counts["REGIONAL-DEVELOPMENT"] == 8
    assert counts["EVERYDAY-ECONOMY"] == 8
    assert counts["CORPORATE-LOANS"] == 5
    assert counts["FIXED-BONDS"] == 4
    assert counts["FLOATING-BONDS"] == 4
    assert counts["PROJECT-FINANCE"] == 4
    assert counts["LEASING-BOOK"] == 4
    assert counts["EQUITY-ROTATION"] == 5
    assert counts["SYNTHETIC-STORIES-V1-2026-09-11"] > 0


# -- a library event with monthly lags ---------------------------------------------------


OIL_FACTORS = ["credit.revenue", "credit.cogs", "credit.capex"]


def _answer(event_id, factors) -> dict:
    """The prepared answer of a library event as the causal step returns it."""
    from msa.agents.causal import _prepared_response
    from msa.agents.ingest import fragment
    from msa.contracts import SourceDocument

    event = json.loads((build_catalog.SYNTHETIC / "events" / f"{event_id}.json").read_text("utf-8"))
    context = {
        "positions": [{"factors": [{"factor_id": f, "key": None} for f in factors]}],
        "factors": [
            {"factor_id": f, "label": f, "scope": "graph", "unit": "fraction"} for f in factors
        ],
    }
    part = fragment(event["text"], "event")
    document = SourceDocument(
        doc_id=event_id.lower(), sha256=part.sha256, mime="text/plain", fragments=[part]
    )
    return _prepared_response(document, event["mock_answer"], context)


def test_the_oil_event_reaches_its_factors_after_different_months():
    graph = _answer("OIL-SUPPLY-DRONE-RISK", OIL_FACTORS)["graph"]
    kinds = {node["id"]: node["kind"] for node in graph["nodes"]}
    lags = sorted(
        edge["lag_months"]
        for edge in graph["edges"]
        if kinds[edge["src"]] == "sector" and kinds[edge["dst"]] == "factor"
    )
    # Price and security costs after a month, lost output after three, repairs after five.
    assert lags == [1, 1, 3, 5]


def test_the_oil_event_keeps_all_four_scenario_parameters():
    scenario = _answer("OIL-SUPPLY-DRONE-RISK", OIL_FACTORS)["scenario"]
    assert set(scenario) == {"oil_price", "platform_damage", "security_cost", "platform_repair"}
    assert scenario["platform_damage"]["high"] < 0 < scenario["oil_price"]["low"]


# -- a portfolio with covenants -----------------------------------------------------------


def test_sgzh_credit_holds_one_corporate_loan_on_its_own_snapshot():
    sgzh = bundle("SGZH-CREDIT")
    assert [p.position_id for p in sgzh.positions] == ["LOAN-SGZH"]
    assert [i.instrument_type for i in sgzh.instruments] == ["corp_loan"]
    assert sgzh.portfolio.snapshot_id == SGZH_SNAPSHOT
    assert SGZH_SNAPSHOT == build_catalog.OWN_SNAPSHOTS["SGZH-CREDIT"][0]


def test_the_sgzh_loan_carries_its_two_covenants():
    covenants = bundle("SGZH-CREDIT").instruments[0].terms["covenants"]
    by_metric = {c["metric"]: c for c in covenants}
    assert set(by_metric) == {"icr", "nd_ebitda"}
    assert by_metric["icr"]["operator"] == "ge"
    assert by_metric["icr"]["threshold"] == 1.5
    assert by_metric["nd_ebitda"]["operator"] == "le"
    assert by_metric["nd_ebitda"]["threshold"] == 4.0
    for covenant in covenants:
        assert covenant["unit"] == "ratio"
        assert covenant["test_dates"] == build_catalog.QUARTER_ENDS


def test_a_loan_written_without_covenants_has_an_empty_covenant_list():
    assert bundle("OIL-CREDIT").instruments[0].terms["covenants"] == []


def test_the_themed_snapshot_does_not_gain_the_sgzh_company():
    # A seeded snapshot never changes: SGZH's data goes to its own snapshot instead.
    themed = snapshot(build_catalog.SNAPSHOT_ID)
    assert not [item for item in themed.items if item.subject == "SGZH"]
    statements = [
        item
        for item in snapshot(SGZH_SNAPSHOT).items
        if item.subject == "SGZH" and item.kind == "financial_statement"
    ]
    assert len(statements) == 1
    assert statements[0].values["credit_limit"].value > 0
    assert statements[0].values["cash_floor"].value > 0


# -- a library event through one sector per factor -----------------------------------------

PULP_FACTORS = ["credit.logistics", "credit.cogs", "credit.working_capital", "credit.interest"]


def test_the_pulp_event_reaches_each_factor_with_its_own_lag_and_elasticity():
    graph = _answer("PULP-MILL-SQUEEZE", PULP_FACTORS)["graph"]
    kinds = {node["id"]: node["kind"] for node in graph["nodes"]}
    factor_of = {node["id"]: node.get("factor") for node in graph["nodes"]}
    by_factor = {
        factor_of[edge["dst"]]: edge
        for edge in graph["edges"]
        if kinds[edge["src"]] == "sector" and kinds[edge["dst"]] == "factor"
    }
    assert {factor: edge["lag_months"] for factor, edge in by_factor.items()} == {
        "credit.logistics": 2,
        "credit.cogs": 1,
        "credit.working_capital": 1,
        "credit.interest": 0,
    }
    assert {factor: edge["elasticity"]["value"] for factor, edge in by_factor.items()} == {
        "credit.logistics": 0.15,
        "credit.cogs": 0.2,
        "credit.working_capital": 0.6,
        "credit.interest": 0.75,
    }


def test_the_pulp_event_keeps_its_four_scenario_parameters_with_their_units():
    scenario = _answer("PULP-MILL-SQUEEZE", PULP_FACTORS)["scenario"]
    assert {name: spec["unit"] for name, spec in scenario.items()} == {
        "wood_freight": "fraction",
        "pulping_chemicals": "fraction",
        "export_payment_delay": "days",
        "key_rate": "fraction",
    }
