"""The monthly signal a scenario parameter sends through the economic graph to one asset.

A ``graph``-scope factor enters at a channel node and reaches the asset through the sector
its activity falls under (deepest match on its OKVED branch); the temporal graph spreads the
shock over the months by the edges' lags (spec 3). A factor node shared by several sectors
carries to the asset only the shock of its own sector. The calculation and the scenario
preview use this one method, so the analyst sees the shock the assets will receive.
"""

import numpy as np

from .graph_adapter import coordinate, temporal_graph
from .okved import okved_covers
from .transmission import direct_input, relative_change


def factor_signal(graph, parameter, factor, okved, value, horizon, *, flags) -> np.ndarray | None:
    """The signal of ``parameter`` (moving ``factor``, a ``FactorSpec``) for ``okved``.

    ``None`` when the parameter's channel does not reach that factor through the sector.
    The signal is a log factor for proportional factors and days or rate points for
    additive ones.
    """
    source = parameter.channel
    target, depth = target_node(graph, factor.factor_id, okved, source)
    if target is None or source not in {node.id for node in graph.nodes}:
        return None
    temporal = temporal_graph(own_sectors(graph, target, okved, depth), factor, horizon)
    raw = np.asarray(value, dtype=float)
    natural = np.broadcast_to(raw[..., None], raw.shape + (horizon,))
    source_node = next(node for node in temporal.nodes if node.id == source)
    # Day and rate shocks enter in their own units and keep them through the graph; the
    # final edge's declared conversion supplies the factor's unit (graph_adapter).
    additive = coordinate(factor)[0] == "additive"
    direct = natural if additive else direct_input(source_node, natural)
    return temporal.propagate({source: direct}, horizon=horizon, flags=flags)[target]


def factor_change(factor, signal) -> np.ndarray:
    """A factor signal as the change a model reads: relative, or days and rate points."""
    return signal if coordinate(factor)[0] == "additive" else relative_change(signal)


def target_node(graph, factor_id, okved, source):
    """The factor node of ``factor_id`` that ``source`` reaches through this asset's sector.

    Sectors match the asset by the OKVED hierarchy, as the exposure selects assets; the
    deepest match wins. A factor node of another sector never carries its shock to this
    asset. Returns the node and the depth of the match (``0`` for a sectorless node).
    """
    nodes = {node.id: node for node in graph.nodes}
    best, best_depth, sectorless = None, 0, []
    for node in graph.nodes:
        if node.kind != "factor" or node.factor != factor_id:
            continue
        if not reachable(graph, source, node.id):
            continue
        sectors = [
            nodes[edge.src].okved
            for edge in graph.edges
            if edge.dst == node.id and edge.src in nodes and nodes[edge.src].okved
        ]
        if not sectors:
            sectorless.append(node.id)
            continue
        depth = max(okved_covers(sector, okved) for sector in sectors)
        if depth > best_depth:
            best, best_depth = node.id, depth
    if best is not None:
        return best, best_depth
    # A graph with a single factor node need not include a sector node.
    return (sectorless[0] if len(sectorless) == 1 else None), 0


def own_sectors(graph, target, okved, depth):
    """The graph without the edges into ``target`` from sectors other than the asset's own.

    A factor node shared by several sectors sums their shocks; the asset takes only those of
    the sectors that cover it at the matched ``depth``. Several sectors of its own industry
    (different channels) still add up.
    """
    okveds = {node.id: node.okved for node in graph.nodes if node.okved}
    edges = [
        edge
        for edge in graph.edges
        if not (
            edge.dst == target
            and edge.src in okveds
            and okved_covers(okveds[edge.src], okved) < depth
        )
    ]
    return graph.model_copy(update={"edges": edges})


def reachable(graph, source, target) -> bool:
    seen, stack = {source}, [source]
    while stack:
        current = stack.pop()
        for edge in graph.edges:
            if edge.src != current or edge.dst in seen:
                continue
            if edge.dst == target:
                return True
            seen.add(edge.dst)
            stack.append(edge.dst)
    return False
