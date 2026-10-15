"""``equity.sector``: a graph-scope factor reaching a share through its issuer's OKVED.

The sector factor carries no key of its own (spec ``SECTOR_FACTOR`` in
``msa.plugins.equity.model``): a scenario parameter names a channel of the event graph, and
the signal travels event -> channel -> sector (OKVED) -> factor through the edges' signs and
elasticities before it reaches the share as ``beta_sector`` times the sector's log change.
"""

import json
import math
from datetime import date

import pytest

from demo import catalog as demo_catalog
from demo.catalog import CATALOG, SYNTHETIC
from msa.agents.base import AgentError
from msa.agents.causal import CausalAgent, _prepared_response
from msa.agents.ingest import fragment
from msa.contracts import DataSnapshot, SourceDocument, TransmissionGraph
from msa.contracts.causal_answer import CausalOutput
from msa.contracts.domain import contexts
from msa.engine.causal_context import portfolio_context
from msa.engine.exposure import scenario_coverage
from msa.engine.runner import run_batch
from msa.platform.registry import registry
from msa.plugin_sdk import FactorRequirement, RunOptions
from msa.plugin_sdk.testing import graph_reaching
from msa.plugins.equity.demo import cases
from msa.plugins.equity.model import MARKET, SECTOR, ShareFactorStress

AS_OF = date(2026, 9, 11)
EVIDENCE = [{"kind": "document", "source_id": "S", "locator": "l", "fragment_sha256": "a" * 64}]


@pytest.fixture
def case():
    (item,) = cases()
    return item


def edge(src, dst, *, sign=1, elasticity=None, lag=0):
    return {
        "src": src,
        "dst": dst,
        "sign": sign,
        "elasticity": elasticity or {"family": "point", "value": 1.0},
        "lag_months": lag,
        "evidence": EVIDENCE,
    }


def run(bundle, snapshot, scenario, graph=None, *, points=64, seed=20260911):
    reg = registry()
    sectors = {party.party_id: party.okved for party in bundle.parties}
    return run_batch(
        contexts(bundle),
        snapshot,
        scenario,
        graph,
        as_of=AS_OF,
        horizon=12,
        seed=seed,
        registry=reg,
        sector_of=sectors.get,
        points=points,
        replicates=8,
        options=reg.run_options("demo"),
    )


def result(batch, position_id):
    return next(r for r in batch.results if r.position_id == position_id)


def no_residual(snapshot: DataSnapshot) -> DataSnapshot:
    raw = snapshot.model_dump(mode="json")
    for item in raw["items"]:
        if item["kind"] == "sensitivity":
            item["values"]["residual_volatility"]["value"] = 0.0
    return DataSnapshot.model_validate(raw)


def sector_graph(okved, *, elasticity=None, sign=1, lag=0):
    """``event -> channel -> sector(okved) -> factor(equity.sector)``, one path."""
    return TransmissionGraph.model_validate(
        {
            "event_id": "event",
            "nodes": [
                {"id": "event", "kind": "event", "label": "e"},
                {"id": "channel", "kind": "channel", "label": "c"},
                {"id": "sector", "kind": "sector", "label": okved, "okved": okved},
                {"id": "factor", "kind": "factor", "label": "f", "factor": "equity.sector"},
            ],
            "edges": [
                edge("event", "channel"),
                edge("channel", "sector"),
                edge("sector", "factor", elasticity=elasticity, sign=sign, lag=lag),
            ],
            "factor_elasticity": {},
        }
    )


def point_sector_scenario(value, *, channel="channel"):
    return {
        "sector": {
            "kind": "point",
            "value": value,
            "unit": "fraction",
            "factor": "equity.sector",
            "channel": channel,
        }
    }


def oil_position(case):
    return next(p for p in contexts(case.bundle) if p.position_id == "SHARE-OIL")


def contribution(share, factor_id):
    return next(c for c in share.details["factor_contributions"] if c["factor_id"] == factor_id)


# -- 1. requirements: the sector factor carries no key, the market factor keeps its index ----


def test_the_sector_requirement_has_no_key_while_the_market_one_keeps_its_index(case):
    position = oil_position(case)
    options = RunOptions(as_of=AS_OF, horizon=12)
    needs = ShareFactorStress().requirements(position, options)
    sector = next(f for f in needs.factors if f.factor_id == SECTOR)
    market = next(f for f in needs.factors if f.factor_id == MARKET)
    assert isinstance(sector, FactorRequirement) and sector.key is None
    assert market.key == "MOEX"


# -- 2. a point channel change reaches the share through its OKVED, scaled by the edge -------


def test_a_point_channel_change_reaches_the_share_through_its_okved(case):
    graph = sector_graph("06.10", elasticity={"family": "point", "value": 0.5})
    scenario = point_sector_scenario(-0.1)
    batch = run(case.bundle, case.snapshot, scenario, graph)
    oil = result(batch, "SHARE-OIL")
    assert oil.execution == "completed"
    assert oil.details["central"]["log_return"] == pytest.approx(
        oil.details["beta_sector"] * 0.5 * math.log1p(-0.1)
    )
    assert "factor_not_in_scenario:equity.sector" not in oil.flags


# -- 3. OKVED hierarchy: the deepest matching sector node reaches the share ------------------


def test_okved_hierarchy_picks_the_matching_sector(case):
    scenario = point_sector_scenario(-0.1)

    # A two-digit sector node ("06") still covers the 06.10 issuer.
    shallow = run(case.bundle, case.snapshot, scenario, sector_graph("06"))
    oil = result(shallow, "SHARE-OIL")
    assert oil.details["central"]["log_return"] == pytest.approx(
        oil.details["beta_sector"] * math.log1p(-0.1)
    )
    assert "factor_not_in_scenario:equity.sector" not in oil.flags

    # A sector node of another activity reaches the US tech share, never the oil producer.
    other = run(case.bundle, case.snapshot, scenario, sector_graph("62.01"))
    oil = result(other, "SHARE-OIL")
    tech = result(other, "SHARE-US-TECH")
    assert "factor_not_in_scenario:equity.sector" in oil.flags
    assert contribution(oil, SECTOR)["contribution"] == pytest.approx(0.0)
    assert "factor_not_in_scenario:equity.sector" not in tech.flags
    assert tech.details["central"]["log_return"] == pytest.approx(
        tech.details["beta_sector"] * math.log1p(-0.1)
    )


# -- 4. an inverse edge (sign -1) flips the sector's log change ------------------------------


def test_an_inverse_edge_flips_the_sector_log_change(case):
    graph = sector_graph("06.10", sign=-1)
    scenario = point_sector_scenario(-0.1)
    batch = run(case.bundle, case.snapshot, scenario, graph)
    oil = result(batch, "SHARE-OIL")
    assert oil.details["central"]["log_return"] == pytest.approx(
        -oil.details["beta_sector"] * math.log1p(-0.1)
    )


# -- 5. two parameters on two channels reaching the same share add up in log space -----------


def test_two_channels_reaching_the_same_share_add_up(case):
    graph = TransmissionGraph.model_validate(
        {
            "event_id": "event",
            "nodes": [
                {"id": "event", "kind": "event", "label": "e"},
                {"id": "channel1", "kind": "channel", "label": "c1"},
                {"id": "channel2", "kind": "channel", "label": "c2"},
                {"id": "sector", "kind": "sector", "label": "06.10", "okved": "06.10"},
                {"id": "factor", "kind": "factor", "label": "f", "factor": "equity.sector"},
            ],
            "edges": [
                edge("event", "channel1"),
                edge("event", "channel2"),
                edge("channel1", "sector"),
                edge("channel2", "sector"),
                edge("sector", "factor"),
            ],
            "factor_elasticity": {},
        }
    )
    scenario = {
        "one": {
            "kind": "point",
            "value": -0.1,
            "unit": "fraction",
            "factor": "equity.sector",
            "channel": "channel1",
        },
        "two": {
            "kind": "point",
            "value": 0.05,
            "unit": "fraction",
            "factor": "equity.sector",
            "channel": "channel2",
        },
    }
    batch = run(case.bundle, case.snapshot, scenario, graph)
    oil = result(batch, "SHARE-OIL")
    assert oil.details["central"]["log_return"] == pytest.approx(
        oil.details["beta_sector"] * (math.log1p(-0.1) + math.log1p(0.05))
    )


# -- 6. a triangular edge elasticity draws different realisations; the central keeps the mode -


def test_a_triangular_edge_elasticity_varies_across_draws_but_centers_on_the_mode(case):
    graph = sector_graph(
        "06.10", elasticity={"family": "triangular", "low": 0.3, "mode": 0.5, "high": 0.8}
    )
    scenario = point_sector_scenario(-0.15)
    batch = run(case.bundle, no_residual(case.snapshot), scenario, graph)
    oil = result(batch, "SHARE-OIL")
    assert oil.details["central"]["log_return"] == pytest.approx(
        oil.details["beta_sector"] * 0.5 * math.log1p(-0.15)
    )
    quantiles = oil.metrics["equity.pnl"].quantiles
    assert quantiles.p05 != pytest.approx(quantiles.p95)


# -- 7. no reach: without a graph, or without a scenario parameter, the flag says so ----------


def test_a_sector_parameter_without_a_graph_does_not_reach_the_share(case):
    scenario = point_sector_scenario(-0.1)
    batch = run(case.bundle, case.snapshot, scenario, graph=None)
    oil = result(batch, "SHARE-OIL")
    assert oil.execution == "completed"
    assert "factor_not_in_scenario:equity.sector" in oil.flags
    assert contribution(oil, SECTOR)["contribution"] == pytest.approx(0.0)


def test_a_graph_without_a_sector_parameter_does_not_reach_the_share(case):
    position = oil_position(case)
    graph = graph_reaching(position.okved, "equity.sector")
    batch = run(case.bundle, case.snapshot, case.scenario, graph)
    oil = result(batch, "SHARE-OIL")
    assert oil.execution == "completed"
    assert "factor_not_in_scenario:equity.sector" in oil.flags


# -- 8. a lag longer than the horizon leaves the sector effect at zero -----------------------


def test_a_lag_past_the_horizon_gives_zero_sector_effect(case):
    graph = sector_graph("06.10", lag=13)
    scenario = point_sector_scenario(-0.1)
    batch = run(case.bundle, case.snapshot, scenario, graph)
    oil = result(batch, "SHARE-OIL")
    assert "factor_not_in_scenario:equity.sector" not in oil.flags
    assert oil.details["central"]["log_return"] == pytest.approx(0.0, abs=1e-9)
    assert contribution(oil, SECTOR)["contribution"] == pytest.approx(0.0)


# -- 9. scenario_coverage: a reachable sector without a parameter blocks the run --------------


def test_scenario_coverage_requires_an_explicit_sector_parameter(case):
    position = oil_position(case)
    graph = graph_reaching(position.okved, "equity.sector")
    options = RunOptions(as_of=AS_OF, horizon=12)

    problems = scenario_coverage([position.model_dump(mode="json")], graph, {}, options, registry())
    assert len(problems) == 1
    assert "Отрасль (акции)" in problems[0]["message"]

    scenario = point_sector_scenario(0.0)
    assert (
        scenario_coverage([position.model_dump(mode="json")], graph, scenario, options, registry())
        == []
    )


# -- 10. CausalAgent._verify_model_context rejects a keyed or sector-less graph factor --------


def causal_context(*references):
    from dataclasses import asdict

    return {
        "factors": [asdict(registry().factors[SECTOR])],
        "positions": [{"factors": [{"factor_id": f, "key": k} for f, k in references]}],
    }


def causal_output(nodes, edges=()):
    return CausalOutput.model_validate(
        {
            "passport": {"event_type": "event"},
            "parameters": {},
            "direct_okved": [],
            "inferred_okved": [],
            "graph": {"event_id": "event", "nodes": list(nodes), "edges": list(edges)},
            "scenario": {},
        }
    )


def test_a_graph_scope_factor_node_with_a_key_is_rejected():
    ctx = causal_context((SECTOR, None))
    nodes = [
        {"id": "event", "kind": "event", "label": "e"},
        {"id": "sector_factor", "kind": "factor", "label": "f", "factor": SECTOR, "key": "metals"},
    ]
    with pytest.raises(AgentError):
        CausalAgent._verify_model_context(causal_output(nodes), ctx)


def test_a_graph_scope_factor_node_reached_without_a_sector_is_rejected():
    ctx = causal_context((SECTOR, None))
    nodes = [
        {"id": "event", "kind": "event", "label": "e"},
        {"id": "channel", "kind": "channel", "label": "c"},
        {"id": "sector_factor", "kind": "factor", "label": "f", "factor": SECTOR},
    ]
    edges = [edge("event", "channel"), edge("channel", "sector_factor")]
    with pytest.raises(AgentError):
        CausalAgent._verify_model_context(causal_output(nodes, edges), ctx)


# -- 11. the RUB-APPRECIATION library event routes "metals" to equity.sector via 24.10 -------


def test_rub_appreciation_mock_answer_routes_metals_to_equity_sector():
    path = CATALOG / SYNTHETIC / "events" / "RUB-APPRECIATION.json"
    event = json.loads(path.read_text("utf-8"))
    part = fragment(event["text"], "p1")
    document = SourceDocument(
        doc_id=part.sha256, sha256=part.sha256, mime="text/plain", fragments=[part]
    )
    raw = [
        position.model_dump(mode="json")
        for position in contexts(demo_catalog.bundle("CURRENCY-RISK"))
    ]
    options = RunOptions(as_of=AS_OF, horizon=12)
    context = portfolio_context(raw, options, registry())
    prepared = _prepared_response(document, event["mock_answer"], context)

    sector_node = next(
        n
        for n in prepared["graph"]["nodes"]
        if n["kind"] == "sector" and n["okved"] == "24.10" and n["id"].startswith("metals_shares__")
    )
    factor_node = next(
        n for n in prepared["graph"]["nodes"] if n["kind"] == "factor" and n["factor"] == SECTOR
    )
    assert "key" not in factor_node
    assert any(
        e["src"] == sector_node["id"] and e["dst"] == factor_node["id"]
        for e in prepared["graph"]["edges"]
    )
    metals = prepared["scenario"]["metals"]
    assert metals["factor"] == SECTOR
    assert metals["unit"] == "fraction"
    assert metals.get("key") is None
