"""msa.validators.v3_reach: every mechanism the event starts must reach a factor."""

from msa.contracts.graph import TransmissionGraph
from msa.validators import validate
from msa.validators.v3_reach import ReachValidator

SHA = "a" * 64


def evidence():
    return [{"kind": "document", "source_id": "S", "locator": "l", "fragment_sha256": SHA}]


def node(node_id, kind, **overrides):
    values = {"id": node_id, "kind": kind, "label": node_id}
    values.update(overrides)
    return values


def edge(src, dst, **overrides):
    values = {
        "src": src,
        "dst": dst,
        "sign": 1,
        "elasticity": {"family": "point", "value": 1.0},
        "lag_months": 0,
        "evidence": evidence(),
    }
    values.update(overrides)
    return values


def graph_payload(*, nodes, edges):
    return {"event_id": "event", "nodes": nodes, "edges": edges, "factor_elasticity": {}}


def factor(node_id="fx"):
    return node(node_id, "factor", factor="market.fx", key="USD/RUB")


def test_dead_end_channel_is_reported_at_its_incoming_edge():
    payload = graph_payload(
        nodes=[node("event", "event"), node("channel", "channel")],
        edges=[edge("event", "channel")],
    )
    verdicts = ReachValidator().check(payload)
    assert len(verdicts) == 1
    assert verdicts[0].ok is False
    assert verdicts[0].rule_id == "V3"
    assert verdicts[0].path == "/edges/0"
    assert "channel" in verdicts[0].message


def test_dead_end_sector_behind_a_channel_that_reaches_a_factor():
    payload = graph_payload(
        nodes=[
            node("event", "event"),
            node("channel", "channel"),
            node("sector", "sector", okved="46.63"),
            factor(),
        ],
        edges=[edge("event", "channel"), edge("channel", "fx"), edge("channel", "sector")],
    )
    verdicts = ReachValidator().check(payload)
    assert [v.path for v in verdicts] == ["/edges/2"]
    assert verdicts[0].ok is False
    assert "sector" in verdicts[0].message


def test_a_node_not_reachable_from_the_event_is_ignored():
    payload = graph_payload(
        nodes=[
            node("event", "event"),
            node("channel", "channel"),
            factor(),
            node("orphan", "channel"),
        ],
        edges=[edge("event", "channel"), edge("channel", "fx")],
    )
    verdicts = ReachValidator().check(payload)
    assert len(verdicts) == 1
    assert verdicts[0].ok is True


def test_two_dead_ends_produce_one_verdict_each():
    payload = graph_payload(
        nodes=[
            node("event", "event"),
            node("c1", "channel"),
            node("c2", "sector", okved="46.63"),
        ],
        edges=[edge("event", "c1"), edge("event", "c2")],
    )
    verdicts = ReachValidator().check(payload)
    assert [v.path for v in verdicts] == ["/edges/0", "/edges/1"]
    assert all(not v.ok and v.rule_id == "V3" for v in verdicts)


def test_a_graph_where_every_chain_ends_in_a_factor_gets_one_ok_verdict():
    payload = graph_payload(
        nodes=[node("event", "event"), node("channel", "channel"), factor()],
        edges=[edge("event", "channel"), edge("channel", "fx")],
    )
    verdicts = ReachValidator().check(payload)
    assert len(verdicts) == 1
    assert verdicts[0].ok is True
    assert verdicts[0].path == "/edges"


def test_check_accepts_a_parsed_transmission_graph():
    graph = TransmissionGraph.model_validate(
        graph_payload(
            nodes=[node("event", "event"), node("channel", "channel"), factor()],
            edges=[edge("event", "channel"), edge("channel", "fx")],
        )
    )
    assert all(v.ok for v in ReachValidator().check(graph))


def test_malformed_payload_returns_no_findings():
    assert ReachValidator().check({"nodes": "not-a-list", "edges": []}) == []
    assert ReachValidator().check({}) == []


def test_dispatcher_validate_includes_v3():
    payload = graph_payload(
        nodes=[node("event", "event"), node("channel", "channel")],
        edges=[edge("event", "channel")],
    )
    verdicts = validate("TransmissionGraph", payload)
    assert any(v.rule_id == "V3" and not v.ok for v in verdicts)
