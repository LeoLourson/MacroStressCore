"""Which positions an approved scenario reaches, whatever their type.

A position is reached through the factors its model is sensitive to. A ``graph``-scope
factor reaches it when the event's graph passes through a sector on the same OKVED branch
as its issuer's activity (``okved_covers``). A direct factor reaches it when the scenario
moves that factor for the position's key: its market index, currency pair or sector. A
position the scenario does not reach is not calculated and is reported as such.
"""

from msa.contracts.domain import PositionContext
from msa.contracts.graph import TransmissionGraph
from msa.contracts.scenario import MacroParameter
from msa.platform.registry import Registry
from msa.plugin_sdk.model import DataRequirements

from .okved import okved_covers


def reached_sectors(graph: TransmissionGraph, factor_ids=None) -> list[str]:
    """OKVED codes of the sectors on the way from the event to any factor node."""
    graph = TransmissionGraph.model_validate(graph)
    sectors = {node.id: node.okved for node in graph.nodes if node.kind == "sector"}
    reached = set()
    for node in graph.nodes:
        if node.kind != "factor" or (factor_ids is not None and node.factor not in factor_ids):
            continue
        for path in graph.simple_paths(graph.event_id, node.id):
            reached.update(edge.src for edge in path if edge.src in sectors)
    return sorted(sectors[node_id] for node_id in reached)


def reasons(
    context: PositionContext,
    requirements: DataRequirements,
    graph: TransmissionGraph | None,
    parameters: dict[str, MacroParameter],
    registry: Registry,
) -> list[str]:
    """Why the scenario reaches the position; empty when it does not."""
    found = []
    graph_factors = [
        item
        for item in requirements.factors
        if registry.factors.get(item.factor_id)
        and registry.factors[item.factor_id].scope == "graph"
    ]
    if graph_factors and graph is not None and context.okved:
        depth = max(
            (
                okved_covers(s, context.okved)
                for s in reached_sectors(graph, {item.factor_id for item in graph_factors})
            ),
            default=0,
        )
        if depth:
            found.append(f"graph_sector:{context.okved}")
    for item in requirements.factors:
        spec = registry.factors.get(item.factor_id)
        if spec is None or spec.scope == "graph":
            continue
        for name, parameter in sorted(parameters.items()):
            if parameter.factor == item.factor_id and (
                item.key is None or parameter.key == item.key
            ):
                found.append(f"factor:{name}")
    return found


def missing_direct_scenario(context, requirements, graph, parameters, registry) -> list[str]:
    """Every affected factor needs a numerical scenario, whatever plugin supplies it.

    Direct nodes describe a factor/key even before its magnitude is known. Historical
    graphs without those nodes still retain affected issuers with unmapped model inputs.
    """
    if graph is None:
        return []
    missing = []
    for item in requirements.factors:
        spec = registry.factors.get(item.factor_id)
        if spec is None:
            continue
        targets = [
            node
            for node in graph.nodes
            if node.kind == "factor"
            and node.factor == item.factor_id
            and node.key == item.key
            and graph.simple_paths(graph.event_id, node.id)
        ]
        if spec.scope == "graph":
            targets = [
                node
                for node in targets
                if context.okved
                and any(
                    okved_covers(sector.okved, context.okved)
                    and graph.simple_paths(graph.event_id, sector.id)
                    and graph.simple_paths(sector.id, node.id)
                    for sector in graph.nodes
                    if sector.kind == "sector"
                )
            ]
        if not targets:
            continue
        matching = [
            p for p in parameters.values() if p.factor == item.factor_id and p.key == item.key
        ]
        if spec.scope == "graph":
            ids = {node.id for node in graph.nodes}
            matching = [
                p
                for p in matching
                if p.channel in ids
                and any(graph.simple_paths(p.channel, node.id) for node in targets)
            ]
        if not matching:
            missing.append(spec.label + (f": {item.key}" if item.key is not None else ""))
    if missing:
        return missing
    if (
        not context.okved
        or not any(okved_covers(code, context.okved) for code in reached_sectors(graph))
        or reasons(context, requirements, graph, parameters, registry)
    ):
        return []
    direct = [
        item
        for item in requirements.factors
        if item.factor_id in registry.factors and registry.factors[item.factor_id].scope != "graph"
    ]
    return [f"{registry.factors[item.factor_id].label}: {item.key}" for item in direct]


def scenario_coverage(positions, graph, parameters, options, registry) -> list[dict]:
    """Review errors for sectors reached by a graph but absent from model scenarios."""
    try:
        graph = TransmissionGraph.model_validate(graph)
        parsed = {
            name: MacroParameter.model_validate(
                {k: v for k, v in spec.items() if k in MacroParameter.model_fields}
            )
            for name, spec in (parameters or {}).items()
        }
    except (ValueError, TypeError):
        return []  # Ordinary graph/scenario validation owns malformed drafts.
    problems = []
    for raw in positions:
        position = PositionContext.model_validate(raw)
        try:
            needs = registry.model_for(position).requirements(position, options)
        except (KeyError, ValueError):
            continue  # Schema/model errors are diagnosed by the dispatcher.
        missing = missing_direct_scenario(position, needs, graph, parsed, registry)
        if missing:
            problems.append(
                {
                    "rule_id": "SCENARIO",
                    "ok": False,
                    "path": "/macro_parameters",
                    "message": f"{position.position_id}: граф указывает влияние на позицию, "
                    "но для модели позиции не задано изменение факторов. "
                    "Добавьте параметр сценария: " + "; ".join(missing) + ". "
                    "Нулевое влияние также нужно задать явно. Потери пока не оценены.",
                }
            )
    return problems
