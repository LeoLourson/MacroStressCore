"""The conformance check every plugin passes: declarations, schemas, outputs, determinism.

``check_plugin`` reads the plugin's declarations and calculates each of its demo cases
through the platform's own dispatcher, so a plugin is judged by the same path a run takes:

- declarations: schemas produce JSON Schema, editor fields name a known target and unit,
  instrument types have a default model;
- the case's bundle satisfies the plugin's schemas and its snapshot is dated consistently;
- every position the case marks as calculable completes, carries its model's required
  metrics in the declared units, has sources for its numbers, and contributes realisations
  of the run's size;
- the calculation is deterministic (same seed, same numbers) and does not depend on the
  order of the positions;
- the slices aggregate.

Helpers for a plugin's own tests (``src/msa/plugins/<id>/tests``), so they need nothing
from the core's modules: ``calculate_case`` runs a demo case (or a variant of it) through
the platform's dispatcher, ``tools_of`` gives the functions of a plugin's MCP server,
``workflow_problems`` compiles every workflow with the plugin's agents switched on, and
``graph_reaching`` builds the smallest economic graph an event can have: the event, one
channel, one sector and one factor node.
"""

import json
from dataclasses import dataclass

from msa.contracts.domain import contexts
from msa.contracts.units import is_unit

from .specs import EDITOR_UNIT_ALIASES


@dataclass(frozen=True)
class Finding:
    plugin_id: str
    check: str
    message: str
    case: str = ""

    def __str__(self):
        where = f" [{self.case}]" if self.case else ""
        return f"{self.plugin_id}{where} {self.check}: {self.message}"


def _declarations(plugin) -> list[Finding]:
    findings = []

    def fail(check, message):
        findings.append(Finding(plugin.plugin_id, check, message))

    for spec in plugin.instrument_types:
        for name, schema in (("terms", spec.terms_schema), ("position", spec.position_schema)):
            try:
                schema.model_json_schema()
            except Exception as exc:  # noqa: BLE001 - reported as a finding
                fail("schema", f"{spec.type_id} {name} schema has no JSON Schema: {exc}")
        for group in spec.editor:
            for field in (*group.fields, *(c for f in group.fields for c in f.columns)):
                target = field.target
                if target not in ("terms", "position") and not target.startswith("snapshot:"):
                    fail("editor", f"{spec.type_id}.{field.name} has an unknown target {target}")
                if (
                    field.unit is not None
                    and field.unit not in EDITOR_UNIT_ALIASES
                    and not is_unit(field.unit)
                ):
                    fail("units", f"{spec.type_id}.{field.name} has an unknown unit {field.unit}")
    for model in plugin.models:
        if not model.required_metrics:
            fail("outputs", f"{model.model_id} declares no required metric")
    return findings


def graph_reaching(sector_okved: str, factor_id: str):
    """An event graph whose one path reaches ``factor_id`` in the sector ``sector_okved``."""
    from msa.contracts.evidence import Evidence
    from msa.contracts.graph import Edge, Node, PointDistribution, TransmissionGraph

    evidence = [Evidence(kind="document", source_id="S", locator="l", fragment_sha256="a" * 64)]

    def edge(src, dst):
        return Edge(
            src=src,
            dst=dst,
            sign=1,
            elasticity=PointDistribution(value=1.0),
            lag_months=0,
            evidence=evidence,
        )

    return TransmissionGraph(
        event_id="event",
        nodes=[
            Node(id="event", kind="event", label="e"),
            Node(id="channel", kind="channel", label="c"),
            Node(id="sector", kind="sector", label="s", okved=sector_okved),
            Node(id="factor", kind="factor", label="f", factor=factor_id),
        ],
        edges=[edge("event", "channel"), edge("channel", "sector"), edge("sector", "factor")],
    )


def _fingerprint(results) -> str:
    return json.dumps(
        {r.position_id: r.model_dump(mode="json", exclude={"code_sha256"}) for r in results},
        sort_keys=True,
    )


def calculate_case(
    case,
    registry=None,
    *,
    positions=None,
    seed: int = 20260911,
    points: int = 64,
    replicates: int = 8,
    horizon: int = 12,
):
    """The case calculated by the platform: a batch with ``results`` (one per position),
    ``draws``, ``exposures`` and ``realisations``. ``positions`` reorders or narrows the
    case's positions; replace ``case.scenario`` (``dataclasses.replace``) to try a shock."""
    from msa.contracts.graph import TransmissionGraph
    from msa.engine.runner import run_batch
    from msa.platform.registry import registry as current

    registry = registry or current()
    graph = None if case.graph is None else TransmissionGraph.model_validate(case.graph)
    sectors = {party.party_id: party.okved for party in case.bundle.parties}
    return run_batch(
        contexts(case.bundle) if positions is None else positions,
        case.snapshot,
        case.scenario,
        graph,
        as_of=case.bundle.portfolio.as_of or case.snapshot.as_of,
        horizon=horizon,
        seed=seed,
        registry=registry,
        sector_of=sectors.get,
        points=points,
        replicates=replicates,
        options=registry.run_options("demo"),
    )


def tools_of(spec) -> dict:
    """Tool name -> the function a plugin's MCP server (``McpServerSpec``) defines; call it
    with ``audit=None`` to test what it answers without the gateway."""
    from msa.platform.registry import mcp_tools

    tools, problems = mcp_tools(spec)
    if problems:
        raise ValueError("; ".join(problems))
    return tools


def workflow_problems(plugin, registry=None) -> list[str]:
    """What stops a workflow from compiling with the plugin's agents switched on."""
    from msa.graph.compiler import check as check_workflow
    from msa.platform.registry import registry as current

    registry = registry or current()
    agents = [a.agent_id for a in plugin.agents if not a.core]
    return [
        f"{plugin.plugin_id} workflow {workflow.workflow_id}: {problem}"
        for workflow in registry.workflows.values()
        for problem in check_workflow(workflow, registry, agents)
    ]


def check_plugin(plugin, registry=None, *, points: int = 64, replicates: int = 8):
    """Every problem found with ``plugin``; an empty list means it conforms."""
    from msa.db.repositories.portfolios import check_bundle
    from msa.engine.aggregation import aggregate_slices
    from msa.platform.registry import registry as current

    registry = registry or current()
    findings = _declarations(plugin)
    if plugin.demo is None:
        if plugin.instrument_types:
            findings.append(
                Finding(plugin.plugin_id, "demo", "an asset plugin must ship a demo case")
            )
        return findings
    for case in plugin.demo():

        def fail(check, message, case=case):
            findings.append(Finding(plugin.plugin_id, check, message, case.name))

        for problem in check_bundle(case.bundle, registry):
            fail("schema", problem)
        positions = contexts(case.bundle)

        def run(order, case=case):
            return calculate_case(
                case, registry, positions=order, points=points, replicates=replicates
            )

        first = run(positions)
        second = run(positions)
        if _fingerprint(first.results) != _fingerprint(second.results):
            fail("determinism", "the same inputs and seed gave different results")
        reordered = run(list(reversed(positions)))
        if _fingerprint(first.results) != _fingerprint(reordered.results):
            fail("order", "the result of a position depends on the order of the positions")
        size = points * replicates
        for result in first.results:
            if result.position_id not in case.completes:
                continue
            if result.execution != "completed":
                fail(
                    "outputs",
                    f"{result.position_id} did not complete: "
                    + "; ".join(
                        f"{d.code} {d.message}".strip()
                        for d in result.diagnostics
                        if d.severity == "error"
                    ),
                )
                continue
            model = registry.model(result.model_id)
            for metric in model.required_metrics:
                if metric not in result.metrics:
                    fail("outputs", f"{result.position_id} lacks required metric {metric}")
            if not result.sources:
                fail("provenance", f"{result.position_id} names no source of its numbers")
            if not result.input_sources:
                fail("provenance", f"{result.position_id} names no source of its inputs")
            for slice_id in model.slices:
                values = first.draws.get((result.position_id, slice_id))
                entering = [c for c in result.contributions if c.slice_id == slice_id and c.enters]
                if entering and (values is None or len(values) != size):
                    fail(
                        "shape", f"{result.position_id} gives no {size} realisations to {slice_id}"
                    )
        try:
            aggregate_slices(
                f"check-{case.name}",
                first.results,
                draws=first.draws,
                exposures=first.exposures,
                registry=registry,
                base_currency=case.bundle.portfolio.base_currency,
                as_of=case.bundle.portfolio.as_of or case.snapshot.as_of,
                horizon=12,
                seed=20260911,
                scenario_id=first.realisations.scenario_id,
                macro_draws_sha256=first.realisations.macro_draws_sha256,
            )
        except Exception as exc:  # noqa: BLE001 - reported as a finding
            fail("aggregation", f"{type(exc).__name__}: {exc}")
    return findings


def check_all(registry=None, **kwargs) -> list[Finding]:
    from msa.platform.registry import registry as current

    registry = registry or current()
    return [
        f for plugin in registry.plugins.values() for f in check_plugin(plugin, registry, **kwargs)
    ]
