"""The contract graph as a typed temporal graph (spec 3): one per factor a shock is sent to."""

import numpy as np

from .transmission import (
    Conversion,
    DelayKernel,
    TemporalEdge,
    TemporalGraph,
    TemporalNode,
)

NO_PATH_FLAG = "factor_not_reached"


def coordinate(factor) -> tuple[str, str]:
    """The coordinate a factor's signal travels in and the quantity it arrives as (spec 3.1).

    Additive factors (days of working capital, rate points) keep their own unit along the
    path; relative and log factors travel as log factors.
    """
    if factor.application == "additive":
        return "additive", factor.quantity
    return "log_factor", "relative_change"


def central_elasticity(distribution) -> float:
    """Central value of an edge elasticity distribution."""
    family = getattr(distribution, "family", None)
    if family == "point":
        return float(distribution.value)
    if family == "triangular":
        return float(distribution.mode)
    if family == "uniform":
        return float((distribution.low + distribution.high) / 2.0)
    if family == "lognormal":
        return float(np.exp(distribution.mu + distribution.sigma**2 / 2.0))
    raise ValueError(f"unknown elasticity family: {family!r}")


def temporal_graph(contract_graph, factor, horizon: int) -> TemporalGraph:
    """Build the typed temporal graph that carries shocks to one ``factor`` (a ``FactorSpec``).

    A scenario parameter names exactly one factor, so every node on the way to it is
    evaluated in that factor's coordinate. Where the factor is additive but the path is
    proportional, the final edge carries an explicit declared conversion (spec 3.1).
    """
    coordinate_, kind = coordinate(factor)
    driver_ids = {
        node.id
        for node in contract_graph.nodes
        if node.kind == "factor" and node.factor == factor.factor_id
    }
    nodes = [
        TemporalNode(
            id=node.id,
            coordinate=coordinate_ if node.id in driver_ids else "log_factor",
            kind=kind if node.id in driver_ids else "relative_change",
        )
        for node in contract_graph.nodes
    ]
    edges = []
    for edge in contract_graph.edges:
        into_driver = edge.dst in driver_ids
        conversion = None
        if into_driver and coordinate_ == "additive":
            # A day or rate-point shock is already in the driver's unit and the path's
            # elasticities scale it on the way; the last edge only declares the unit.
            conversion = Conversion(to_kind=kind, scale=1.0)
        edges.append(
            TemporalEdge(
                src=edge.src,
                dst=edge.dst,
                sign=int(edge.sign),
                sensitivity=abs(central_elasticity(edge.elasticity)),
                # A lag outside the calculation horizon produces no in-horizon
                # response. Clamping it to H-1 would invent an effect in the final
                # month and violate temporal propagation semantics.
                kernel=DelayKernel.fixed(int(edge.lag_months)),
                conversion=conversion,
            )
        )
    return TemporalGraph(nodes=nodes, edges=edges)
