"""The run line on a synthetic portfolio and event, from the event text to the report.

Everything is the production line except the two people and the LLM: the causal answer is
the graph and scenario of the synthetic event (what an analyst would confirm), the analyst
confirms them at the graph stop — where the platform's own scenario checks still apply —
and the risk manager approves the report. Exposure, the scenario set, every model, the
portfolio slices and the report run as in the demo namespace (synthetic PD calibration).
"""

from dataclasses import dataclass, field
from itertools import count

from msa.agents import Agents
from msa.agents.advisory import AdvisoryAgent
from msa.agents.aggregate import AggregateAgent
from msa.agents.causal_output import CausalOutput
from msa.agents.draw_macro import DrawMacroAgent
from msa.agents.exposure import ExposureAgent, LocalResolver
from msa.agents.ingest import fragment
from msa.agents.quant import QuantAgent
from msa.contracts import SourceDocument
from msa.contracts.domain import contexts
from msa.db.repositories.runs import MemoryRunRepository
from msa.graph.checkpoint import build_checkpointer
from msa.graph.interrupts import pending_interrupt, resume_run, start_run
from msa.graph.workflow import build_graph
from msa.platform.registry import registry

from .build import AS_OF, Event

SEED = 20260911
MC_POINTS = 8192
AUTHOR_OF_DECISION = "sanity:risk-manager"
_RUNS = count(1)


class TextIngest:
    def run(self, payload) -> SourceDocument:
        part = fragment(payload["text"], "p1")
        return SourceDocument(
            doc_id="doc:" + part.sha256[:16],
            sha256=part.sha256,
            mime="text/plain",
            fragments=[part],
        )


class LibraryIngest:
    """The text as the platform ingests it: the document id is the text's sha256, so the mock
    profile recognises a library event and answers with its prepared graph and scenario."""

    def run(self, payload) -> SourceDocument:
        part = fragment(payload["text"], "p1")
        return SourceDocument(
            doc_id=part.sha256, sha256=part.sha256, mime="text/plain", fragments=[part]
        )


class AnalystGraph:
    """The causal step's answer: the event's graph and scenario, cited to the event text."""

    def __init__(self, event: Event):
        self.event = event

    def run_structured(self, payload) -> CausalOutput:
        document = SourceDocument.model_validate(payload["document"])
        source = document.fragments[0]
        evidence = [
            {
                "kind": "document",
                "source_id": document.doc_id,
                "locator": source.locator,
                "fragment_sha256": source.sha256,
            }
        ]
        return CausalOutput.model_validate(
            {
                "passport": {"event_type": self.event.event_type},
                "parameters": {},
                "direct_okved": self.event.okved,
                "inferred_okved": [],
                "graph": self.event.graph(evidence),
                "scenario": self.event.scenario,
            }
        )


class NoApprovedThresholds:
    """A fresh stand: every rule runs on its declared threshold, and the report says so."""

    def current(self):
        return {}


@dataclass
class Outcome:
    """What one run produced, as plain data."""

    run_id: str
    stage: str
    #: The violations the analyst saw at the graph stop, before and after confirming.
    violations: list[dict] = field(default_factory=list)
    blocked: list[dict] = field(default_factory=list)
    reached: list[str] = field(default_factory=list)
    results: dict[str, dict] = field(default_factory=dict)
    portfolio: dict | None = None
    report: dict | None = None
    #: position id -> slice id -> loss realisations in the run's shared order.
    draws: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    #: The run's scenario set as the draw node recorded it (``spec``, ``seed``, sizes).
    scenario: dict | None = None
    error: str | None = None


def run(
    bundle,
    snapshot,
    event: Event,
    *,
    seed=SEED,
    mc_points=MC_POINTS,
    horizon=12,
    ingest=None,
    causal=None,
) -> Outcome:
    """``causal`` and ``ingest`` replace the analyst's graph of ``event`` and the plain text."""
    reg = registry()
    run_id = f"sanity-{next(_RUNS)}-{event.event_id}"
    sectors = {party.party_id: party.okved for party in bundle.parties}
    agents = Agents(
        ingest=ingest or TextIngest(),
        causal=causal or AnalystGraph(event),
        exposure=ExposureAgent(registry=reg, resolver=LocalResolver(snapshot, sectors.get)),
        draw_macro=DrawMacroAgent(registry=reg),
        quant=QuantAgent(registry=reg),
        aggregate=AggregateAgent(registry=reg),
        advisory=AdvisoryAgent(
            registry=reg,
            thresholds_repository=NoApprovedThresholds(),
            options=reg.run_options("demo"),
        ),
    )
    chosen = contexts(bundle)
    payload = {
        "run_id": run_id,
        "text": event.text,
        "seed": seed,
        "mc_points": mc_points,
        "horizon": horizon,
        "mode": "demo",
        "as_of": AS_OF.isoformat(),
        "portfolio_id": bundle.portfolio.portfolio_id,
        "snapshot_id": snapshot.snapshot_id,
        "base_currency": bundle.portfolio.base_currency,
        "portfolio_positions": [c.model_dump(mode="json") for c in chosen],
        "position_names": {
            c.position_id: (c.issuer.name if c.issuer else c.instrument.name) for c in chosen
        },
    }
    with build_checkpointer() as saver:
        graph = build_graph(
            saver,
            agents=agents,
            repository=MemoryRunRepository(),
            registry=reg,
            options=reg.run_options("demo"),
        )
        state = start_run(graph, payload)
        outcome = Outcome(run_id=run_id, stage="graph")
        stop = _stop(graph, run_id)
        if stop is None or stop["kind"] != "human_fix_graph":
            outcome.error = f"no graph stop: status {state.get('status')}, {state.get('errors')}"
            return outcome
        outcome.violations = stop["violations"]
        state = resume_run(
            graph,
            run_id,
            {"graph": stop["graph"], "macro_parameters": stop["macro_parameters"]},
        )
        stop = _stop(graph, run_id)
        if stop is not None and stop["kind"] == "human_fix_graph":
            # The platform refused the confirmed scenario: nothing was calculated.
            outcome.blocked = stop["violations"]
            return outcome
        if stop is None or stop["kind"] != "human_approval":
            outcome.error = f"no report stop: status {state.get('status')}, {state.get('errors')}"
            return outcome
        state = resume_run(graph, run_id, {"approved": True, "approved_by": AUTHOR_OF_DECISION})
        outcome.stage = state.get("status", "?")
        outcome.reached = sorted(p["position"]["position_id"] for p in state.get("positions") or [])
        outcome.results = {r["position_id"]: r for r in state.get("sorted_results") or []}
        outcome.portfolio = state.get("portfolio_result")
        outcome.draws = {
            item["position_id"]: item["draws"] for item in state.get("position_draws") or []
        }
        scenario = state.get("scenario_set")
        if scenario is not None:
            outcome.scenario = (
                scenario if isinstance(scenario, dict) else scenario.model_dump(mode="json")
            )
        report = state.get("report")
        outcome.report = report if isinstance(report, dict) else report.model_dump(mode="json")
        return outcome


def _stop(graph, run_id):
    pending = pending_interrupt(graph, run_id)
    return pending[0]["payload"] if pending else None
