"""Test doubles built on the real contracts, and the run inputs the graph tests share.

The production agents are used wherever they are fast and need no network: exposure, the
scenario set, the models, the portfolio slices and the report. What is replaced is the LLM
(a scripted causal answer) and, where a test is about orchestration rather than numbers,
the calculation.
"""

from copy import deepcopy

from demo import catalog as demo_catalog
from msa.agents import Agents
from msa.agents.advisory import AdvisoryAgent
from msa.agents.aggregate import AggregateAgent
from msa.agents.causal_output import CausalOutput
from msa.agents.draw_macro import DrawMacroAgent
from msa.agents.exposure import ExposureAgent, LocalResolver
from msa.agents.ingest import fragment
from msa.agents.quant import QuantAgent, QuantInput, not_calculated
from msa.contracts import DataSnapshot, PortfolioBundle, SourceDocument
from msa.contracts.domain import contexts
from msa.graph.interrupts import pending_interrupt, resume_run
from msa.platform.registry import registry

SEED = 20260911
AS_OF = "2026-09-11"
SNAPSHOT_ID = "SYNTHETIC-2026-09-11"

SCENARIO = {
    "demand_drop": {
        "label": "Падение спроса",
        "kind": "triangular",
        "low": -0.15,
        "mode": -0.10,
        "high": -0.05,
        "unit": "fraction",
        "channel": "channel",
        "factor": "credit.revenue",
    }
}

THRESHOLDS = {
    "credit.R1": {
        "metric": "credit.icr_p50",
        "operator": "lt",
        "threshold": 1.0,
        "actions": ["restructure"],
    },
    "credit.R2": {
        "metric": "credit.covenant_breach_probability",
        "operator": "ge",
        "threshold": 0.5,
        "actions": ["add_collateral", "covenant_talks"],
    },
    "credit.R3": {
        "metric": "credit.delta_pd_p50",
        "operator": "ge",
        "threshold": 5.0,
        "actions": ["limit_cut"],
    },
    "credit.R4": {
        "metric": "credit.rate_fx_channel_share",
        "operator": "ge",
        "threshold": 0.5,
        "actions": ["hedge"],
    },
    "credit.R5": {
        "metric": "credit.delta_el_p50",
        "operator": "gt",
        "threshold": 0.0,
        "actions": ["watchlist"],
    },
}
THRESHOLDS = {
    rule_id: {
        "rule_id": rule_id,
        "revision": 1,
        "unit": "",
        "fallback_only": rule_id == "credit.R5",
        **rule,
    }
    for rule_id, rule in THRESHOLDS.items()
}


def bundle(portfolio="MULTI-ASSET") -> PortfolioBundle:
    return demo_catalog.bundle(portfolio)


def snapshot() -> DataSnapshot:
    return demo_catalog.snapshot(SNAPSHOT_ID)


def positions(portfolio="MULTI-ASSET", ids=None) -> list[dict]:
    return [
        context.model_dump(mode="json")
        for context in contexts(bundle(portfolio))
        if ids is None or context.position_id in ids
    ]


def run_input(run_id, *, portfolio="MULTI-ASSET", ids=None, **overrides) -> dict:
    chosen = positions(portfolio, ids if ids is not None else {"LOAN-MACHINERY", "LOAN-FERTILIZER"})
    names = {p["position"]["position_id"]: (p.get("issuer") or {}).get("name", "") for p in chosen}
    return {
        "run_id": run_id,
        "text": "Правительство повышает утилизационный сбор на импортную технику.",
        "seed": SEED,
        "mc_points": 8192,
        "horizon": 12,
        "mode": "demo",
        "as_of": AS_OF,
        "portfolio_id": portfolio,
        "snapshot_id": SNAPSHOT_ID,
        "base_currency": "RUB",
        "portfolio_positions": chosen,
        "position_names": names,
        **overrides,
    }


class TextIngest:
    """The event text as one addressable fragment."""

    def run(self, payload) -> SourceDocument:
        text = payload["text"]
        part = fragment(text, "p1")
        return SourceDocument(
            doc_id="doc:" + part.sha256[:16],
            sha256=part.sha256,
            mime="text/plain",
            fragments=[part],
        )


class ScriptedCausal:
    """The causal agent's structured answer without an LLM: event -> channel -> sectors."""

    def __init__(self, scenario=None, *, factor="credit.revenue"):
        self.scenario = SCENARIO if scenario is None else scenario
        self.factor = factor
        self.calls = []

    def run_structured(self, payload) -> CausalOutput:
        self.calls.append(deepcopy(payload))
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
        sectors = sorted(set(payload["okved_scope"]))
        nodes = [
            {"id": "event", "kind": "event", "label": "событие"},
            {"id": "channel", "kind": "channel", "label": "канал"},
            {"id": "factor", "kind": "factor", "label": "показатель", "factor": self.factor},
        ]
        edges = [_edge("event", "channel", evidence)]
        for index, okved in enumerate(sectors):
            sector = f"sector{index}"
            nodes.append({"id": sector, "kind": "sector", "label": okved, "okved": okved})
            edges += [_edge("channel", sector, evidence), _edge(sector, "factor", evidence)]
        return CausalOutput.model_validate(
            {
                "passport": {"event_type": "Утилизационный сбор"},
                "parameters": {},
                "direct_okved": sectors,
                "inferred_okved": [],
                "graph": {
                    "event_id": "event",
                    "nodes": nodes,
                    "edges": edges,
                    "factor_elasticity": {},
                },
                "scenario": deepcopy(self.scenario),
            }
        )


class SkippedQuant:
    """Orchestration tests: every position returns a reviewable result without numbers."""

    def __init__(self):
        self.calls = []

    def run(self, payload: QuantInput):
        self.calls.append(payload.context.position_id)
        return not_calculated(
            payload, registry(), "test:calculation_skipped", status="needs_review"
        )


class FixedThresholds:
    def current(self):
        return deepcopy(THRESHOLDS)


def agents(*, calculate=False, **overrides) -> Agents:
    """The run's agents with a scripted LLM; ``calculate`` runs the models for every position."""
    reg = registry()
    data = snapshot()
    sectors = {}
    for name in ("MULTI-ASSET", "ATYPICAL-BORROWERS", "LOAD-TEST"):
        sectors.update({p.party_id: p.okved for p in bundle(name).parties})
    values = {
        "ingest": TextIngest(),
        "causal": ScriptedCausal(),
        "exposure": ExposureAgent(registry=reg, resolver=LocalResolver(data, sectors.get)),
        "draw_macro": DrawMacroAgent(registry=reg),
        "quant": QuantAgent(registry=reg) if calculate else SkippedQuant(),
        "aggregate": AggregateAgent(registry=reg),
        "advisory": AdvisoryAgent(
            registry=reg,
            thresholds_repository=FixedThresholds(),
            options=reg.run_options("demo"),
        ),
    }
    values.update(overrides)
    return Agents(**values)


def stop(graph, run_id) -> dict:
    pending = pending_interrupt(graph, run_id)
    assert pending, "the run is not waiting for a person"
    return pending[0]["payload"]


def confirm(graph, run_id, **answer):
    """The analyst confirms the graph and the proposed scenario at the graph stop."""
    payload = stop(graph, run_id)
    assert payload["kind"] == "human_fix_graph"
    return resume_run(graph, run_id, {"graph": payload["graph"], **answer})


def _edge(src, dst, evidence):
    return {
        "src": src,
        "dst": dst,
        "sign": 1,
        "elasticity": {"family": "point", "value": 1.0},
        "lag_months": 0,
        "evidence": evidence,
    }
