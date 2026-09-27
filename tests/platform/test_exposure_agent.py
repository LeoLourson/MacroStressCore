"""msa.agents.exposure: positions the scenario does not reach are measured, not calculated."""

from msa.agents.exposure import ExposureAgent, LocalResolver
from msa.platform.registry import registry
from msa.plugin_sdk.testing import graph_reaching
from tests.support import AS_OF, SNAPSHOT_ID, bundle, positions, snapshot

REVENUE = {
    "rev": {
        "kind": "point",
        "value": -0.1,
        "unit": "fraction",
        "factor": "credit.revenue",
        "channel": "channel",
    }
}


def exposure(graph, parameters):
    sectors = {party.party_id: party.okved for party in bundle().parties}
    agent = ExposureAgent(registry=registry(), resolver=LocalResolver(snapshot(), sectors.get))
    return agent.run(
        {
            "graph": None if graph is None else graph.model_dump(mode="json"),
            "macro_parameters": parameters,
            "as_of": AS_OF,
            "horizon": 12,
            "snapshot_id": SNAPSHOT_ID,
            "positions": positions(),
        }
    )


def test_unreached_positions_keep_their_exposure_and_reached_ones_are_calculated():
    found = exposure(graph_reaching("46.63", "credit.revenue"), REVENUE)
    assert [p["position"]["position_id"] for p in found["positions"]] == ["LOAN-MACHINERY"]
    assert found["diagnostics"]["LOAN-MACHINERY"]["exposures"] == {"credit.loss": 3000.0}
    unreached = found["unreached_exposures"]
    assert "LOAN-MACHINERY" not in unreached
    assert unreached["LOAN-FERTILIZER"] == {"credit.loss": 1500.0}
    assert set(unreached["SHARE-OIL"]) == {"market.pnl"}


def test_without_a_graph_every_position_is_measured_and_none_is_calculated():
    found = exposure(None, {})
    assert found["positions"] == []
    assert found["prepared"] == {}
    assert len(found["unreached_exposures"]) == len(positions())
