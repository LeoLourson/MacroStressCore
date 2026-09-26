"""Write the reference results of the credit model on the demo portfolios.

Every credit position of MULTI-ASSET and ATYPICAL-BORROWERS goes through the platform (the
dispatcher, the credit plugin and the slice aggregator) on one scenario that moves five
drivers through a graph with lags and a triangular elasticity. The inputs, a summary of the
scenario draws and the results go to ``credit_reference.json``; the reference test runs the
same inputs and compares. Rewrite the reference only when a change of the numbers is meant:

    uv run --frozen python -m msa.plugins.credit.tests.capture_reference
"""

import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np

from demo import catalog
from msa.contracts import PortfolioBundle, TransmissionGraph
from msa.contracts.domain import contexts
from msa.engine.aggregation import aggregate_slices
from msa.engine.runner import run_batch
from msa.engine.scenario_set import scenario_set_from_parameters
from msa.platform.registry import registry

from ..families import asset_types

REFERENCE = Path(__file__).with_name("credit_reference.json")
SNAPSHOT_ID = "SYNTHETIC-2026-09-11"
PORTFOLIOS = ("MULTI-ASSET", "ATYPICAL-BORROWERS")
SLICE = "credit.loss"

EVIDENCE = [
    {
        "kind": "document",
        "source_id": "golden-event",
        "locator": "p1",
        "fragment_sha256": hashlib.sha256(b"golden").hexdigest(),
    }
]
#: Channel -> (the driver it moves, the lag of its edge into a sector).
CHANNELS = {
    "ch_demand": ("revenue", 0),
    "ch_costs": ("cogs", 1),
    "ch_rate": ("interest", 2),
    "ch_payments": ("working_capital", 0),
    "ch_capex": ("capex", 1),
}
SCENARIO = {
    "demand": {
        "kind": "triangular",
        "low": -0.18,
        "mode": -0.1,
        "high": -0.03,
        "unit": "fraction",
        "channel": "ch_demand",
        "factor": "credit.revenue",
    },
    "costs": {
        "kind": "uniform",
        "low": 0.02,
        "high": 0.12,
        "unit": "fraction",
        "channel": "ch_costs",
        "factor": "credit.cogs",
    },
    "rate": {
        "kind": "truncated_normal",
        "mean": 0.03,
        "sigma": 0.01,
        "low": 0.0,
        "high": 0.06,
        "unit": "fraction",
        "channel": "ch_rate",
        "factor": "credit.interest",
    },
    "payments": {
        "kind": "triangular",
        "low": 5.0,
        "mode": 15.0,
        "high": 30.0,
        "unit": "days",
        "channel": "ch_payments",
        "factor": "credit.working_capital",
    },
    "capex": {
        "kind": "point",
        "value": 0.1,
        "unit": "fraction",
        "channel": "ch_capex",
        "factor": "credit.capex",
    },
}
SETTINGS = {"as_of": "2026-09-11", "seed": 20260911, "points": 512, "replicates": 8, "horizon": 12}


def _edge(src, dst, *, lag=0, elasticity=None):
    return {
        "src": src,
        "dst": dst,
        "sign": 1,
        "elasticity": elasticity or {"family": "point", "value": 1.0},
        "lag_months": lag,
        "evidence": EVIDENCE,
    }


def graph_for(okveds) -> dict:
    """Every channel reaches every sector of the portfolio; each sector has its own factors."""
    nodes = [{"id": "event", "kind": "event", "label": "событие"}]
    edges = []
    for channel in CHANNELS:
        nodes.append({"id": channel, "kind": "channel", "label": channel})
        edges.append(_edge("event", channel))
    for okved in sorted(okveds):
        sector = "s_" + okved.replace(".", "_")
        nodes.append({"id": sector, "kind": "sector", "label": okved, "okved": okved})
        for channel, (driver, lag) in CHANNELS.items():
            elasticity = (
                {"family": "triangular", "low": 0.5, "mode": 0.8, "high": 1.2}
                if driver == "revenue"
                else None
            )
            edges.append(_edge(channel, sector, lag=lag, elasticity=elasticity))
            target = f"f_{okved.replace('.', '_')}_{driver}"
            nodes.append(
                {"id": target, "kind": "factor", "label": driver, "factor": "credit." + driver}
            )
            edges.append(_edge(sector, target))
    return {"event_id": "event", "nodes": nodes, "edges": edges, "factor_elasticity": {}}


def credit_bundle(portfolio_id) -> PortfolioBundle:
    """The demo portfolio without its shares: the reference covers credit positions."""
    raw = catalog.bundle_data(portfolio_id)
    types = {i["instrument_id"]: i["instrument_type"] for i in raw["instruments"]}
    raw["positions"] = [p for p in raw["positions"] if types[p["instrument_id"]] in asset_types()]
    return PortfolioBundle.model_validate(raw)


def run(portfolio_id, graph, scenario, settings):
    """The batch and the credit slice of one portfolio on the reference inputs."""
    reg = registry()
    bundle = credit_bundle(portfolio_id)
    as_of = date.fromisoformat(settings["as_of"])
    batch = run_batch(
        contexts(bundle),
        catalog.snapshot(SNAPSHOT_ID),
        scenario,
        TransmissionGraph.model_validate(graph),
        as_of=as_of,
        horizon=settings["horizon"],
        seed=settings["seed"],
        registry=reg,
        sector_of={party.party_id: party.okved for party in bundle.parties}.get,
        points=settings["points"],
        replicates=settings["replicates"],
        options=reg.run_options("demo"),
        run_id=f"reference-{portfolio_id}",
    )
    portfolio = aggregate_slices(
        f"reference-{portfolio_id}",
        batch.results,
        draws=batch.draws,
        exposures=batch.exposures,
        registry=reg,
        base_currency="RUB",
        as_of=as_of,
        horizon=settings["horizon"],
        seed=settings["seed"],
        scenario_id=batch.realisations.scenario_id,
        macro_draws_sha256=batch.realisations.macro_draws_sha256,
    )
    return batch, portfolio.slices[SLICE]


def draw_summaries(scenario, settings) -> dict:
    """Per parameter: a summary of its realisations that tolerates last-digit drift."""
    scenario_set = scenario_set_from_parameters(
        scenario, points=settings["points"], replicates=settings["replicates"]
    )
    sampled = scenario_set.sample(settings["seed"])
    result = {}
    for name in sampled.names:
        values = np.asarray(sampled.stacked(name), dtype=float).reshape(-1)
        result[name] = {
            "count": int(values.size),
            "sum": float(values.sum()),
            "sum_sq": float((values**2).sum()),
            "head": [float(v) for v in values[:8]],
            "p05": float(np.percentile(values, 5)),
            "p50": float(np.percentile(values, 50)),
            "p95": float(np.percentile(values, 95)),
        }
    return result


def main():
    out = {
        "note": "Results of the credit model on the demo portfolios MULTI-ASSET and "
        "ATYPICAL-BORROWERS, written by capture_reference.py.",
        **SETTINGS,
        "scenario": SCENARIO,
        "draws": draw_summaries(SCENARIO, SETTINGS),
        "portfolios": {},
    }
    for portfolio_id in PORTFOLIOS:
        bundle = credit_bundle(portfolio_id)
        issuers = {i.instrument_id: i.issuer_id for i in bundle.instruments}
        sectors = {p.party_id: p.okved for p in bundle.parties}
        okveds = {sectors[issuers[p.instrument_id]] for p in bundle.positions}
        graph = graph_for(okveds)
        batch, credit = run(portfolio_id, graph, SCENARIO, SETTINGS)
        out["portfolios"][portfolio_id] = {
            "graph": graph,
            "positions": {
                result.position_id: {
                    "execution": result.execution,
                    "status": result.status,
                    "details": result.details,
                }
                for result in batch.results
            },
            "slice": credit.model_dump(mode="json"),
        }
        print(portfolio_id, [(r.position_id, r.status) for r in batch.results])
        print("  slice", credit.status, credit.loss_quantiles)
    text = json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    REFERENCE.write_text(text, encoding="utf-8")
    print("written", REFERENCE, REFERENCE.stat().st_size)


if __name__ == "__main__":
    main()
