"""msa.contracts.graph: the economic transmission graph (event -> channel -> sector -> factor)."""

import pytest
from pydantic import ValidationError

from msa.contracts.graph import Edge, Node, TransmissionGraph


def evidence():
    return [{"kind": "document", "source_id": "S", "locator": "l", "fragment_sha256": "a" * 64}]


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


def nodes():
    return [
        {"id": "event", "kind": "event", "label": "event"},
        {"id": "channel", "kind": "channel", "label": "channel"},
        {"id": "sector1", "kind": "sector", "label": "s1", "okved": "23.61"},
        {"id": "factor", "kind": "factor", "label": "f", "factor": "credit.revenue"},
    ]


def graph(*, node_list=None, edge_list=None, factor_elasticity=None):
    return TransmissionGraph(
        event_id="event",
        nodes=node_list if node_list is not None else nodes(),
        edges=edge_list
        if edge_list is not None
        else [
            edge("event", "channel"),
            edge("channel", "sector1"),
            edge("sector1", "factor"),
        ],
        factor_elasticity=factor_elasticity or {},
    )


# -- Node ---------------------------------------------------------------------------------


def test_factor_node_requires_factor_field():
    with pytest.raises(ValidationError, match="Only factor nodes must specify factor"):
        Node(id="f", kind="factor", label="f")


def test_non_factor_node_rejects_factor_field():
    with pytest.raises(ValidationError, match="Only factor nodes must specify factor"):
        Node(id="e", kind="event", label="e", factor="credit.revenue")


def test_sector_node_requires_okved():
    with pytest.raises(ValidationError, match="Only sector nodes must specify okved"):
        Node(id="s", kind="sector", label="s")


def test_non_sector_node_rejects_okved():
    with pytest.raises(ValidationError, match="Only sector nodes must specify okved"):
        Node(id="e", kind="event", label="e", okved="23.61")


# -- Edge ---------------------------------------------------------------------------------


def test_edge_sign_must_be_integer_not_bool_or_float():
    with pytest.raises(ValidationError, match="sign must be the integer"):
        Edge(**edge("a", "b", sign=1.0))
    with pytest.raises(ValidationError, match="sign must be the integer"):
        Edge(**edge("a", "b", sign=True))


def test_edge_requires_at_least_one_evidence_item():
    with pytest.raises(ValidationError):
        Edge(**edge("a", "b", evidence=[]))


def test_edge_lag_months_bounds():
    with pytest.raises(ValidationError):
        Edge(**edge("a", "b", lag_months=37))
    with pytest.raises(ValidationError):
        Edge(**edge("a", "b", lag_months=-1))


# -- TransmissionGraph: DAG and reference checks -------------------------------------------


def test_graph_accepts_a_valid_dag():
    g = graph()
    assert g.event_id == "event"


def test_graph_rejects_duplicate_node_ids():
    dup = nodes() + [{"id": "event", "kind": "event", "label": "event2"}]
    with pytest.raises(ValidationError, match="Node IDs must be unique"):
        graph(node_list=dup)


def test_graph_rejects_event_id_not_identifying_an_event_node():
    with pytest.raises(ValidationError, match="event_id must identify an event node"):
        TransmissionGraph(event_id="channel", nodes=nodes(), edges=[])


def test_graph_rejects_factor_elasticity_key_not_a_factor_node():
    with pytest.raises(ValidationError, match="factor_elasticity keys must identify factor nodes"):
        graph(factor_elasticity={"sector1": 1.5})


def test_graph_accepts_factor_elasticity_keyed_by_factor_node():
    g = graph(factor_elasticity={"factor": 1.5})
    assert g.factor_elasticity["factor"] == 1.5


def test_graph_rejects_edge_referencing_unknown_node():
    with pytest.raises(ValidationError, match="Edges must reference existing nodes"):
        graph(edge_list=[edge("event", "nope")])


def test_graph_rejects_duplicate_edges():
    with pytest.raises(ValidationError, match="Duplicate edge"):
        graph(edge_list=[edge("event", "channel"), edge("event", "channel")])


def test_graph_rejects_a_cycle():
    cyclic_nodes = [
        {"id": "event", "kind": "event", "label": "e"},
        {"id": "channel", "kind": "channel", "label": "c"},
    ]
    with pytest.raises(ValidationError, match="acyclic"):
        graph(
            node_list=cyclic_nodes,
            edge_list=[edge("event", "channel"), edge("channel", "event")],
        )


# -- simple_paths ---------------------------------------------------------------------------


def test_simple_paths_finds_the_only_path():
    g = graph()
    paths = g.simple_paths("event", "factor")
    assert len(paths) == 1
    assert [e.dst for e in paths[0]] == ["channel", "sector1", "factor"]


def test_simple_paths_between_adjacent_nodes_is_one_edge():
    g = graph()
    paths = g.simple_paths("event", "channel")
    assert len(paths) == 1
    assert len(paths[0]) == 1


def test_simple_paths_with_no_path_is_empty():
    g = graph()
    assert g.simple_paths("factor", "event") == []


def test_simple_paths_raises_keyerror_for_unknown_node():
    g = graph()
    with pytest.raises(KeyError):
        g.simple_paths("nope", "event")
    with pytest.raises(KeyError):
        g.simple_paths("event", "nope")
