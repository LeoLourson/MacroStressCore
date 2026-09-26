"""The credit models reproduce Track A v3.2 as it stood before the platform migration.

``credit_v3_2.json`` holds the inputs and results captured from the pre-migration code
(``capture_v3_2.py.txt``): every asset of DEMO-1 and DEMO-2 on a scenario that moves five
drivers through a graph with lags and a triangular elasticity, and each portfolio's loss.
The same assets, now parties, instruments, positions and a data snapshot, go through the
platform: the dispatcher, the credit plugin and the slice aggregator.

Documented differences, not regressions:
- the data-quality score is recomputed from the statement on every run (as the exposure
  agent always did in a live run); the captured profiles carried the catalog's score, so
  ``coverage.input_data``, the data axis and the score's source are not compared;
- flags are compared without repetitions (the transmission used to append duplicates);
- the model id is the platform's (``credit.corporate.v3``), no longer ``track_a_v3/...``.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from demo import catalog
from msa.contracts import PortfolioBundle, TransmissionGraph
from msa.contracts.domain import contexts
from msa.engine.aggregation import aggregate_slices
from msa.engine.runner import run_batch
from msa.platform.registry import registry

GOLDEN = json.loads((Path(__file__).with_name("credit_v3_2.json")).read_text("utf-8"))
SNAPSHOT_ID = "DEMO-2026-09-11"
NOT_COMPARED = ("/coverage/input_data", "/axes/4/measures/data_quality", "/input_sources/dq")
TOLERANCE = 1e-9


def graph(old: dict) -> TransmissionGraph:
    """The captured graph in today's contract: driver nodes are factor nodes."""
    value = json.loads(json.dumps(old))
    for node in value["nodes"]:
        if node["kind"] == "driver":
            node["kind"] = "factor"
            node["factor"] = "credit." + node.pop("driver")
    value["factor_elasticity"] = value.pop("driver_elasticity")
    return TransmissionGraph.model_validate(value)


def scenario(old: dict) -> dict:
    return {
        name: {
            **{k: v for k, v in item.items() if k != "driver"},
            "factor": "credit." + item["driver"],
        }
        for name, item in old.items()
    }


def differences(expected, actual, path=""):
    if path.startswith(NOT_COMPARED) or path.endswith("/model_id") or path.endswith("code_sha256"):
        return []
    if isinstance(expected, dict) and isinstance(actual, dict):
        found = []
        for key in sorted(set(expected) | set(actual)):
            if key not in expected or key not in actual:
                found.append(f"{path}/{key}: present on one side only")
            else:
                found += differences(expected[key], actual[key], f"{path}/{key}")
        return found
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [f"{path}: {len(expected)} items, got {len(actual)}"]
        return [
            d
            for i, (a, b) in enumerate(zip(expected, actual, strict=False))
            for d in differences(a, b, f"{path}/{i}")
        ]
    if isinstance(expected, float) and isinstance(actual, float):
        scale = max(1.0, abs(expected), abs(actual))
        return (
            []
            if abs(expected - actual) <= TOLERANCE * scale
            else [f"{path}: {expected} != {actual}"]
        )
    return [] if expected == actual else [f"{path}: {expected!r} != {actual!r}"]


@pytest.fixture(scope="module")
def runs():
    snapshot = catalog.snapshot(SNAPSHOT_ID)
    reg = registry()
    out = {}
    for portfolio_id, captured in GOLDEN["portfolios"].items():
        raw = catalog.bundle_data(portfolio_id)
        # The demo portfolio has since gained shares; the reference covers its credit positions.
        raw["positions"] = [p for p in raw["positions"] if p["position_id"] in captured["assets"]]
        bundle = PortfolioBundle.model_validate(raw)
        sectors = {party.party_id: party.okved for party in bundle.parties}
        batch = run_batch(
            contexts(bundle),
            snapshot,
            scenario(GOLDEN["scenario"]),
            graph(captured["graph"]),
            as_of=date.fromisoformat(GOLDEN["as_of"]),
            horizon=GOLDEN["horizon"],
            seed=GOLDEN["seed"],
            registry=reg,
            sector_of=sectors.get,
            points=GOLDEN["points"],
            replicates=GOLDEN["replicates"],
            options=reg.run_options("demo"),
            run_id=f"golden-{portfolio_id}",
        )
        portfolio = aggregate_slices(
            f"golden-{portfolio_id}",
            batch.results,
            draws=batch.draws,
            exposures=batch.exposures,
            registry=reg,
            base_currency="RUB",
            as_of=date.fromisoformat(GOLDEN["as_of"]),
            horizon=GOLDEN["horizon"],
            seed=GOLDEN["seed"],
            scenario_id=batch.realisations.scenario_id,
            macro_draws_sha256=batch.realisations.macro_draws_sha256,
        )
        out[portfolio_id] = (captured, batch, portfolio)
    return out


@pytest.mark.parametrize("portfolio_id", sorted(GOLDEN["portfolios"]))
def test_every_calculated_position_matches_its_reference(runs, portfolio_id):
    captured, batch, _ = runs[portfolio_id]
    calculated = 0
    for result in batch.results:
        expected = dict(captured["assets"][result.position_id]["result"])
        if expected["model_id"] == "not_calculated":
            # The reference kept it out of the run; so does the platform, with its reason.
            assert result.execution == "not_run" and result.status == expected["status"]
            continue
        calculated += 1
        actual = dict(result.details)
        expected["flags"] = list(dict.fromkeys(expected["flags"]))
        actual["flags"] = list(dict.fromkeys(actual["flags"]))
        assert differences(expected, actual) == [], result.position_id
        assert result.macro_draws_sha256 == expected["macro_draws_sha256"]
    assert calculated == sum(
        1 for item in captured["assets"].values() if item["result"]["model_id"] != "not_calculated"
    )


@pytest.mark.parametrize("portfolio_id", sorted(GOLDEN["portfolios"]))
def test_the_credit_slice_matches_the_reference_portfolio(runs, portfolio_id):
    captured, _, portfolio = runs[portfolio_id]
    old = captured["portfolio"]
    credit = portfolio.slices["credit.loss"]
    pairs = {
        "p05": (credit.loss_quantiles.p05, old["loss_quantiles"]["p05"]),
        "p50": (credit.loss_quantiles.p50, old["loss_quantiles"]["p50"]),
        "p95": (credit.loss_quantiles.p95, old["loss_quantiles"]["p95"]),
        "es95": (credit.expected_shortfall_95, old["expected_shortfall_95"]),
        "mean": (credit.mean_loss, old["mean_loss"]),
        "var95": (credit.value_at_risk_95, old["value_at_risk_95"]),
        "coverage": (credit.coverage.covered_share, old["covered_ead_share"]),
        "hhi": (credit.herfindahl, old["herfindahl"]),
        "sum_p95": (credit.sum_of_individual_p95, old["sum_of_individual_p95"]),
    }
    for name, (actual, expected) in pairs.items():
        assert actual == pytest.approx(expected, rel=TOLERANCE, abs=TOLERANCE), name
    assert credit.status == old["status"]
    assert credit.included == old["included_assets"]
    assert [e.position_id for e in credit.excluded] == [
        e["asset_id"] for e in old["excluded_assets"]
    ]
    assert sorted(credit.flags) == sorted(old["flags"])
    reference = {c["asset_id"]: c for c in old["contributions"]}
    for item in credit.contributions:
        expected = reference[item.position_id]
        assert item.expected_shortfall_contribution == pytest.approx(
            expected["expected_shortfall_contribution"], rel=TOLERANCE, abs=TOLERANCE
        )
        assert item.mean_loss == pytest.approx(expected["mean_loss"], rel=TOLERANCE, abs=TOLERANCE)
