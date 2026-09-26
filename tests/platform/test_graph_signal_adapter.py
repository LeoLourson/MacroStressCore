"""msa.engine.graph_signal and msa.engine.graph_adapter: monthly signal through the graph."""

import numpy as np
import pytest

from msa.contracts.evidence import Evidence
from msa.contracts.graph import (
    Edge,
    LogNormalDistribution,
    Node,
    PointDistribution,
    TransmissionGraph,
    TriangularDistribution,
    UniformDistribution,
)
from msa.contracts.scenario import MacroParameter
from msa.engine.graph_adapter import central_elasticity, coordinate, temporal_graph
from msa.engine.graph_signal import factor_change, factor_signal, reachable, target_node
from msa.plugin_sdk.specs import FactorSpec

HORIZON = 3


def evidence():
    return [Evidence(kind="document", source_id="S", locator="l", fragment_sha256="a" * 64)]


def edge(src, dst, *, sign=1, value=1.0, lag=0):
    return Edge(
        src=src,
        dst=dst,
        sign=sign,
        elasticity=PointDistribution(value=value),
        lag_months=lag,
        evidence=evidence(),
    )


def log_factor(factor_id="credit.revenue"):
    return FactorSpec(
        factor_id=factor_id,
        label="F",
        unit="fraction",
        scope="graph",
        application="relative",
        quantity="relative_change",
    )


def additive_factor(factor_id="credit.working_capital"):
    return FactorSpec(
        factor_id=factor_id,
        label="F",
        unit="days",
        scope="graph",
        application="additive",
        quantity="days",
    )


def parameter(channel="channel", factor="credit.revenue"):
    return MacroParameter(
        kind="point",
        value=0.1,
        unit="fraction",
        factor=factor,
        channel=channel,
    )


def signal_of(g, spec, *, okved=None, value=0.1, channel="channel", param_factor="credit.revenue"):
    return factor_signal(
        g,
        parameter(channel=channel, factor=param_factor),
        spec,
        okved=okved,
        value=value,
        horizon=HORIZON,
        flags=[],
    )


# -- coordinate() -----------------------------------------------------------------------


def test_coordinate_additive_factor_keeps_its_own_quantity():
    assert coordinate(additive_factor()) == ("additive", "days")


def test_coordinate_non_additive_factor_travels_as_log_factor():
    assert coordinate(log_factor()) == ("log_factor", "relative_change")


# -- central_elasticity() ----------------------------------------------------------------


def test_central_elasticity_point():
    assert central_elasticity(PointDistribution(value=2.0)) == 2.0


def test_central_elasticity_triangular_is_the_mode():
    assert central_elasticity(TriangularDistribution(low=0.0, mode=0.5, high=1.0)) == 0.5


def test_central_elasticity_uniform_is_the_midpoint():
    assert central_elasticity(UniformDistribution(low=0.0, high=1.0)) == 0.5


def test_central_elasticity_lognormal():
    dist = LogNormalDistribution(mu=0.0, sigma=1.0)
    assert central_elasticity(dist) == pytest.approx(np.exp(0.0 + 1.0 / 2.0))


def test_central_elasticity_unknown_family_raises():
    class Fake:
        family = "unknown"

    with pytest.raises(ValueError, match="unknown elasticity family"):
        central_elasticity(Fake())


# -- temporal_graph() ---------------------------------------------------------------------


def two_node_graph(elasticity_value=1.0, lag=0, factor_id="credit.revenue"):
    return TransmissionGraph(
        event_id="event",
        nodes=[
            Node(id="event", kind="event", label="e"),
            Node(id="channel", kind="channel", label="c"),
            Node(id="factor", kind="factor", label="f", factor=factor_id),
        ],
        edges=[
            edge("event", "channel"),
            edge("channel", "factor", value=elasticity_value, lag=lag),
        ],
    )


def test_temporal_graph_marks_driver_nodes_in_the_factor_coordinate():
    g = two_node_graph()
    temporal = temporal_graph(g, log_factor(), HORIZON)
    node = temporal.node("factor")
    assert node.coordinate == "log_factor"
    assert node.kind == "relative_change"


def test_temporal_graph_non_driver_nodes_stay_relative_change():
    g = two_node_graph()
    temporal = temporal_graph(g, log_factor(), HORIZON)
    node = temporal.node("channel")
    assert node.coordinate == "log_factor"
    assert node.kind == "relative_change"


def test_temporal_graph_adds_conversion_on_edge_into_an_additive_driver():
    g = two_node_graph(factor_id="credit.working_capital")
    temporal = temporal_graph(g, additive_factor(), HORIZON)
    into_driver = next(e for e in temporal.edges if e.dst == "factor")
    assert into_driver.conversion is not None
    assert into_driver.conversion.to_kind == "days"
    assert into_driver.conversion.scale == 1.0


def test_temporal_graph_no_conversion_when_coordinates_match():
    g = two_node_graph()
    temporal = temporal_graph(g, log_factor(), HORIZON)
    into_driver = next(e for e in temporal.edges if e.dst == "factor")
    assert into_driver.conversion is None


def test_temporal_graph_kernel_reflects_edge_lag():
    g = two_node_graph(lag=2)
    temporal = temporal_graph(g, log_factor(), HORIZON)
    into_driver = next(e for e in temporal.edges if e.dst == "factor")
    assert into_driver.kernel.max_lag == 2


def test_temporal_graph_sensitivity_is_the_absolute_central_elasticity():
    g = two_node_graph(elasticity_value=2.0)
    temporal = temporal_graph(g, log_factor(), HORIZON)
    into_driver = next(e for e in temporal.edges if e.dst == "factor")
    assert into_driver.sensitivity == 2.0
    assert into_driver.gain() == 2.0  # sign +1 keeps the gain positive


# -- factor_signal() / factor_change() -----------------------------------------------------


def test_factor_signal_relative_factor_direct_two_node_path():
    g = two_node_graph()
    signal = signal_of(g, log_factor())
    assert signal is not None
    assert np.allclose(signal, np.log1p(0.1))
    assert np.allclose(factor_change(log_factor(), signal), 0.1)


def test_factor_signal_additive_factor_keeps_its_own_unit():
    g = two_node_graph(factor_id="credit.working_capital")
    signal = signal_of(g, additive_factor(), value=5.0, param_factor="credit.working_capital")
    assert signal is not None
    assert np.allclose(signal, 5.0)
    assert np.allclose(factor_change(additive_factor(), signal), 5.0)


def test_factor_signal_returns_none_when_channel_does_not_reach_the_factor():
    g = TransmissionGraph(
        event_id="event",
        nodes=[
            Node(id="event", kind="event", label="e"),
            Node(id="channel", kind="channel", label="c"),
            Node(id="other_channel", kind="channel", label="oc"),
            Node(id="factor", kind="factor", label="f", factor="credit.revenue"),
        ],
        edges=[
            edge("event", "channel"),
            edge("event", "other_channel"),
            edge("other_channel", "factor"),
        ],
    )
    signal = signal_of(g, log_factor())
    assert signal is None


def test_factor_signal_respects_sector_matching():
    g = TransmissionGraph(
        event_id="event",
        nodes=[
            Node(id="event", kind="event", label="e"),
            Node(id="channel", kind="channel", label="c"),
            Node(id="sector", kind="sector", label="s", okved="23.61"),
            Node(id="factor", kind="factor", label="f", factor="credit.revenue"),
        ],
        edges=[edge("event", "channel"), edge("channel", "sector"), edge("sector", "factor")],
    )
    reached = signal_of(g, log_factor(), okved="23.61")
    unreached = signal_of(g, log_factor(), okved="99.99")
    assert reached is not None
    assert unreached is None


def test_factor_signal_scales_with_edge_sensitivity():
    g = two_node_graph(elasticity_value=2.0)
    signal = signal_of(g, log_factor())
    assert np.allclose(signal, 2.0 * np.log1p(0.1))


# -- target_node(): deepest-sector choice and sectorless fallback --------------------------


def sectored_graph(*sectors_and_factors):
    """``sectors_and_factors``: list of (sector_id, okved, factor_node_id)."""
    nodes = [
        Node(id="event", kind="event", label="e"),
        Node(id="channel", kind="channel", label="c"),
    ]
    edges = [edge("event", "channel")]
    for sector_id, okved, factor_node in sectors_and_factors:
        nodes.append(Node(id=sector_id, kind="sector", label=sector_id, okved=okved))
        nodes.append(
            Node(id=factor_node, kind="factor", label=factor_node, factor="credit.revenue")
        )
        edges.append(edge("channel", sector_id))
        edges.append(edge(sector_id, factor_node))
    return TransmissionGraph(event_id="event", nodes=nodes, edges=edges)


def test_target_node_picks_the_deepest_okved_match():
    g = sectored_graph(("s1", "23.60", "f1"), ("s2", "23.61", "f2"))
    result = target_node(g, "credit.revenue", "23.61", "channel")
    assert result == "f2"


def test_target_node_returns_none_when_no_sector_matches():
    g = sectored_graph(("s1", "11.11", "f1"))
    assert target_node(g, "credit.revenue", "23.61", "channel") is None


def test_target_node_sectorless_single_factor_fallback():
    g = TransmissionGraph(
        event_id="event",
        nodes=[
            Node(id="event", kind="event", label="e"),
            Node(id="channel", kind="channel", label="c"),
            Node(id="factor", kind="factor", label="f", factor="credit.revenue"),
        ],
        edges=[edge("event", "channel"), edge("channel", "factor")],
    )
    assert target_node(g, "credit.revenue", "any-okved", "channel") == "factor"


def test_target_node_ambiguous_sectorless_factors_return_none():
    nodes = [
        Node(id="event", kind="event", label="e"),
        Node(id="channel", kind="channel", label="c"),
        Node(id="factor1", kind="factor", label="f1", factor="credit.revenue"),
        Node(id="factor2", kind="factor", label="f2", factor="credit.revenue"),
    ]
    edges = [edge("event", "channel"), edge("channel", "factor1"), edge("channel", "factor2")]
    g = TransmissionGraph(event_id="event", nodes=nodes, edges=edges)
    assert target_node(g, "credit.revenue", "any", "channel") is None


def test_target_node_ignores_unreachable_factor_nodes():
    nodes = [
        Node(id="event", kind="event", label="e"),
        Node(id="channel", kind="channel", label="c"),
        Node(id="other", kind="channel", label="oc"),
        Node(id="factor", kind="factor", label="f", factor="credit.revenue"),
    ]
    edges = [edge("event", "channel"), edge("event", "other"), edge("other", "factor")]
    g = TransmissionGraph(event_id="event", nodes=nodes, edges=edges)
    assert target_node(g, "credit.revenue", "any", "channel") is None


# -- reachable() ---------------------------------------------------------------------------


def test_reachable_true_along_a_path():
    g = two_node_graph()
    assert reachable(g, "event", "factor")


def test_reachable_false_without_a_path():
    g = two_node_graph()
    assert not reachable(g, "factor", "event")


def test_reachable_false_for_disconnected_nodes():
    g = sectored_graph(("s1", "23.60", "f1"), ("s2", "23.61", "f2"))
    assert not reachable(g, "f1", "f2")
