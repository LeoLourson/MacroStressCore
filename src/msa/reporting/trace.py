"""Where a number of the report comes from: its value, the nodes that produced it, sources.

The lineage runs from the report back through the aggregation, the position's calculation,
its data preparation and the scenario the analyst confirmed. The sources are those of the
report that the number actually rests on: the position's own inputs, the event's path to
its sector and the scenario parameters that reached it.
"""

from msa.contracts import CalculationResult, PositionContext, TransmissionGraph
from msa.contracts.evidence import Evidence
from msa.contracts.report import Report
from msa.engine.okved import okved_depth

from .numbers import resolve_pointer
from .tree import metric_tree


def _latest(rows, node):
    matches = [row for row in rows if row["node"] == node]
    return max(matches, key=lambda row: row["attempt"]) if matches else None


def _graph_sources(graph, okved):
    sectors = {
        node.id for node in graph.nodes if node.kind == "sector" and okved_depth(okved, node.okved)
    }
    evidence = []
    for factor in (node.id for node in graph.nodes if node.kind == "factor"):
        for path in graph.simple_paths(graph.event_id, factor):
            if any(edge.dst in sectors or edge.src in sectors for edge in path):
                evidence.extend(item for edge in path for item in edge.evidence)
    return evidence


def _source_key(evidence):
    return (evidence.kind, evidence.source_id, evidence.locator, evidence.fragment_sha256)


def trace_number(run_id, metric_path, repository, registry=None):
    from msa.agents.advisory import channel_factors
    from msa.platform.registry import registry as current

    registry = registry or current()
    rows = repository.list_node_results(run_id)
    report_row = _latest(rows, "advisory_agent")
    if report_row is None:
        raise KeyError(run_id)
    report = Report.model_validate(report_row["payload"]["report"])
    ref = next((n for n in report.numbers if n.metric_path == metric_path), None)
    if ref is None:
        raise KeyError(metric_path)
    row = _latest(rows, "aggregate")
    if row is None:
        raise KeyError(metric_path)
    payload = row["payload"]
    causal_row = _latest(rows, "causal_agent")
    review_row = _latest(rows, "human_fix_graph")
    scenario_row = review_row or causal_row
    parameters = (scenario_row or {}).get("payload", {}).get("macro_parameters") or {}
    results = [CalculationResult.model_validate(r) for r in payload.get("sorted_results", [])]
    tree = metric_tree(
        results,
        payload.get("portfolio_result"),
        registry=registry,
        context={"channel_factors": channel_factors(parameters)},
    )
    value = resolve_pointer(tree, metric_path)
    selected = report.sources
    lineage = [{"node": row["node"], "attempt": row["attempt"]}]
    if metric_path.startswith("/positions/"):
        position_id = metric_path.split("/")[2].replace("~1", "/").replace("~0", "~")
        exposure_row = _latest(rows, "exposure_profiler")
        quant_row = _latest(rows, f"quant_agent/{position_id}")
        if exposure_row is None or quant_row is None:
            raise KeyError(f"Missing upstream journal for {position_id}")
        result = next((r for r in results if r.position_id == position_id), None)
        if result is None:
            raise KeyError(position_id)
        exposure = exposure_row["payload"]
        position = next(
            PositionContext.model_validate(p)
            for p in exposure["positions"]
            if p["position"]["position_id"] == position_id
        )
        reach = (exposure.get("reach") or {}).get(position_id, [])
        upstream = list(result.sources)
        lineage.extend(
            {"node": upstream_row["node"], "attempt": upstream_row["attempt"]}
            for upstream_row in (quant_row, exposure_row)
        )
        if scenario_row is not None:
            graph = TransmissionGraph.model_validate(scenario_row["payload"]["graph"])
            direct = {item.partition(":")[2] for item in reach if item.startswith("factor:")}
            if any(item.startswith("graph_sector:") for item in reach) and position.okved:
                upstream.extend(_graph_sources(graph, position.okved))
            for name, parameter in parameters.items():
                channel = parameter.get("channel")
                via_graph = (
                    channel is not None
                    and position.okved
                    and any(
                        node.kind == "sector"
                        and okved_depth(position.okved, node.okved)
                        and graph.simple_paths(channel, node.id)
                        for node in graph.nodes
                    )
                )
                if name in direct or via_graph or parameter.get("factor") is None:
                    upstream.extend(
                        Evidence.model_validate(e) for e in parameter.get("evidence", [])
                    )
            lineage.append({"node": scenario_row["node"], "attempt": scenario_row["attempt"]})
        keys = {_source_key(item) for item in upstream}
        selected = [item for item in report.sources if _source_key(item) in keys]
    return {
        "run_id": run_id,
        "metric_path": metric_path,
        "value": value,
        "node": row["node"],
        "attempt": row["attempt"],
        "number_ref": ref.model_dump(mode="json"),
        "lineage": lineage,
        "sources": [e.model_dump(mode="json") for e in selected],
    }
