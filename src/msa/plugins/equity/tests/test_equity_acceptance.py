"""Acceptance of the equity plugin.

- a share is calculated without EAD, LGD or a financial statement;
- zero shocks keep the price; quantity scales value and P&L; an FX shock moves the result
  in the base currency by exactly the rate change;
- two positions of one security read the same realisations, and the order of positions
  does not change any result;
- a price dated after the valuation date, a missing exchange rate and sensitivities
  estimated against another index are rejected with the reason;
- the market slice adds realisations before quantiles; credit and market never mix.
"""

import math
from copy import deepcopy
from datetime import date

import numpy as np
import pytest

from demo import catalog
from msa.agents.exposure import ExposureAgent, LocalResolver
from msa.contracts import DataSnapshot, PortfolioBundle, TransmissionGraph
from msa.contracts.domain import contexts
from msa.engine.aggregation import aggregate_slices
from msa.engine.dispatch import not_run
from msa.engine.exposure import scenario_coverage
from msa.engine.runner import run_batch
from msa.platform.registry import registry
from msa.plugin_sdk.model import Diagnostics, RunOptions
from msa.plugin_sdk.testing import graph_reaching
from msa.plugins.equity.demo import cases

AS_OF = date(2026, 9, 11)


@pytest.fixture
def case():
    (item,) = cases()
    return item


def zero(scenario):
    return {
        name: {k: v for k, v in item.items() if k not in {"low", "mode", "high"}}
        | {"kind": "point", "value": 0.0}
        for name, item in scenario.items()
    }


def run(bundle, snapshot, scenario, graph=None, *, points=64, seed=20260911):
    reg = registry()
    sectors = {party.party_id: party.okved for party in bundle.parties}
    return run_batch(
        contexts(bundle),
        snapshot,
        scenario,
        graph,
        as_of=AS_OF,
        horizon=12,
        seed=seed,
        registry=reg,
        sector_of=sectors.get,
        points=points,
        replicates=8,
        options=reg.run_options("demo"),
    )


def result(batch, position_id):
    return next(r for r in batch.results if r.position_id == position_id)


def no_residual(snapshot: DataSnapshot) -> DataSnapshot:
    raw = snapshot.model_dump(mode="json")
    for item in raw["items"]:
        if item["kind"] == "sensitivity":
            item["values"]["residual_volatility"]["value"] = 0.0
    return DataSnapshot.model_validate(raw)


def test_a_share_needs_no_ead_lgd_or_statement(case):
    batch = run(case.bundle, case.snapshot, case.scenario)
    for position_id in ("SHARE-OIL", "SHARE-US-TECH"):
        share = result(batch, position_id)
        assert share.execution == "completed" and share.status == "ok"
        assert not any(m.startswith("credit.") for m in share.metrics)
        assert not any(k in share.details for k in ("ead", "lgd", "credit"))
        assert {c.slice_id for c in share.contributions} == {"market.pnl"}


def test_operating_shock_does_not_silently_drop_a_share_in_the_reached_sector(case):
    issuer = case.bundle.parties[0]
    graph = graph_reaching(issuer.okved, "credit.cogs")
    scenario = {
        "costs": {
            "kind": "point",
            "value": 0.1,
            "unit": "fraction",
            "factor": "credit.cogs",
            "channel": "channel",
        }
    }
    exposed = expose(case, scenario, graph)
    position = next(c for c in contexts(case.bundle) if c.position_id in exposed["diagnostics"])
    share = not_run(
        position,
        Diagnostics.model_validate(exposed["diagnostics"][position.position_id]),
        registry(),
        as_of=AS_OF,
        horizon=12,
        seed=42,
    )
    assert share.execution == "not_run"
    assert share.status == "needs_review"
    assert share.metrics == {}
    assert "scenario_factor_missing" in share.flags
    problems = scenario_coverage(
        [c.model_dump(mode="json") for c in contexts(case.bundle)],
        graph,
        scenario,
        RunOptions(as_of=AS_OF, horizon=12),
        registry(),
    )
    assert problems and "Потери пока не оценены" in problems[0]["message"]


def test_an_explicit_sector_shock_including_zero_unlocks_the_share(case):
    position = contexts(case.bundle)[0]
    graph = graph_reaching(position.okved, "equity.sector")
    for shock in (0.0, -0.1):
        scenario = {
            "sector": {
                "kind": "point",
                "value": shock,
                "unit": "fraction",
                "factor": "equity.sector",
                "channel": "channel",
            }
        }
        problems = scenario_coverage(
            [position.model_dump(mode="json")],
            graph,
            scenario,
            RunOptions(as_of=AS_OF, horizon=12),
            registry(),
        )
        assert problems == []
        batch = run(case.bundle, case.snapshot, scenario, graph)
        share = result(batch, position.position_id)
        assert share.execution == "completed"
        assert share.metrics["equity.pnl"].quantiles is not None
        # The sector's change arrives through the issuer's OKVED and moves the price by β_s.
        assert share.details["central"]["log_return"] == pytest.approx(
            share.details["beta_sector"] * math.log1p(shock)
        )


def test_unrelated_sector_is_not_marked_as_missing_scenario(case):
    graph = graph_reaching("99", "credit.cogs")
    assert expose(case, {}, graph)["positions"] == []


def expose(case, scenario, graph):
    sectors = {party.party_id: party.okved for party in case.bundle.parties}
    agent = ExposureAgent(registry=registry(), resolver=LocalResolver(case.snapshot, sectors.get))
    return agent.run(
        {
            "positions": [c.model_dump(mode="json") for c in contexts(case.bundle)],
            "graph": graph.model_dump(mode="json"),
            "macro_parameters": scenario,
            "as_of": AS_OF.isoformat(),
            "horizon": 12,
            "snapshot_id": case.snapshot.snapshot_id,
        }
    )


def test_zero_shocks_keep_the_price_and_value(case):
    batch = run(case.bundle, no_residual(case.snapshot), zero(case.scenario))
    for position_id in ("SHARE-OIL", "SHARE-US-TECH"):
        share = result(batch, position_id)
        value = share.metrics["equity.value_current"].value
        horizon = share.metrics["equity.value_horizon"].quantiles
        assert horizon.p05 == pytest.approx(value) and horizon.p95 == pytest.approx(value)
        dividends = share.metrics["equity.dividends"].value
        pnl = share.metrics["equity.pnl"].quantiles
        # Against today's value only the declared dividends remain; against the base, nothing.
        assert pnl.p50 == pytest.approx(dividends)
        assert share.metrics["equity.pnl_vs_base"].quantiles.p50 == pytest.approx(0.0, abs=1e-9)
        assert share.details["central"]["price"] == pytest.approx(share.details["price"])


def test_quantity_scales_value_and_pnl(case):
    doubled = case.bundle.model_copy(deep=True)
    for position in doubled.positions:
        position.params["quantity"]["value"] *= 2
    base = run(case.bundle, case.snapshot, case.scenario)
    twice = run(doubled, case.snapshot, case.scenario)
    for position_id in ("SHARE-OIL", "SHARE-US-TECH"):
        a, b = result(base, position_id), result(twice, position_id)
        for metric in ("equity.value_current", "equity.dividends"):
            assert b.metrics[metric].value == pytest.approx(2 * a.metrics[metric].value)
        for q in ("p05", "p50", "p95"):
            assert getattr(b.metrics["equity.pnl"].quantiles, q) == pytest.approx(
                2 * getattr(a.metrics["equity.pnl"].quantiles, q)
            )


def test_an_fx_shock_moves_the_base_currency_value_by_the_rate(case):
    scenario = zero(case.scenario)
    scenario["rub"] = {**scenario["rub"], "value": 0.1}
    batch = run(case.bundle, no_residual(case.snapshot), scenario)
    dollar = result(batch, "SHARE-US-TECH")
    value = dollar.metrics["equity.value_current"].value
    assert dollar.metrics["equity.value_horizon"].quantiles.p50 == pytest.approx(
        value * math.exp(0.1)
    )
    rouble = result(batch, "SHARE-OIL")
    assert rouble.metrics["equity.value_horizon"].quantiles.p50 == pytest.approx(
        rouble.metrics["equity.value_current"].value
    )
    # The case moves no sector factor: the result says so rather than treating it silently.
    assert "factor_not_in_scenario:equity.sector" in rouble.flags
    fx_part = next(
        c for c in dollar.details["factor_contributions"] if c["factor_id"] == "market.fx"
    )
    assert fx_part["contribution"] == pytest.approx(value * (math.exp(0.1) - 1))


def test_two_positions_of_one_security_share_their_realisations(case):
    bundle = case.bundle.model_copy(deep=True)
    extra = deepcopy(bundle.positions[0])
    extra.position_id = "SHARE-OIL-2"
    bundle.positions.append(extra)
    batch = run(PortfolioBundle.model_validate(bundle.model_dump()), case.snapshot, case.scenario)
    one = np.asarray(batch.draws["SHARE-OIL", "market.pnl"])
    two = np.asarray(batch.draws["SHARE-OIL-2", "market.pnl"])
    assert np.array_equal(one, two)


def test_the_order_of_positions_changes_nothing(case):
    forward = run(case.bundle, case.snapshot, case.scenario)
    backward_bundle = case.bundle.model_copy(deep=True)
    backward_bundle.positions.reverse()
    backward = run(backward_bundle, case.snapshot, case.scenario)
    for position_id in ("SHARE-OIL", "SHARE-US-TECH"):
        assert (
            result(forward, position_id).model_dump() == result(backward, position_id).model_dump()
        )


def _without(snapshot, kind):
    raw = snapshot.model_dump(mode="json")
    raw["items"] = [i for i in raw["items"] if i["kind"] != kind]
    return DataSnapshot.model_validate(raw)


def test_a_missing_exchange_rate_stops_the_foreign_share_only(case):
    batch = run(case.bundle, _without(case.snapshot, "fx_rate"), case.scenario)
    dollar = result(batch, "SHARE-US-TECH")
    assert dollar.execution == "not_run"
    assert any(f.startswith("fx_missing:USD/RUB") for f in dollar.flags)
    assert result(batch, "SHARE-OIL").execution == "completed"


def test_a_price_dated_after_the_valuation_date_is_not_used(case):
    raw = case.snapshot.model_dump(mode="json")
    raw["as_of"] = "2026-09-30"
    for item in raw["items"]:
        if item["kind"] == "price" and item["subject"] == "SHARE-OIL":
            item["observed_on"] = "2026-09-20"
    batch = run(case.bundle, DataSnapshot.model_validate(raw), case.scenario)
    oil = result(batch, "SHARE-OIL")
    assert oil.execution == "not_run"
    assert "data_dated_after_as_of:price" in oil.flags


def test_sensitivities_of_another_index_are_rejected(case):
    raw = case.snapshot.model_dump(mode="json")
    for item in raw["items"]:
        if item["kind"] == "sensitivity" and item["subject"] == "SHARE-OIL":
            item["attributes"]["market_index"] = "RTS"
    batch = run(case.bundle, DataSnapshot.model_validate(raw), case.scenario)
    oil = result(batch, "SHARE-OIL")
    assert oil.execution == "not_run" and "calibration_mismatch" in oil.flags


def test_an_absent_dividend_declaration_is_not_read_as_zero(case):
    batch = run(case.bundle, _without(case.snapshot, "dividend"), case.scenario)
    assert all(r.execution == "not_run" for r in batch.results)
    assert all("data_missing:dividend" in r.flags for r in batch.results)


def test_the_market_slice_adds_realisations_before_quantiles(case):
    batch = run(case.bundle, case.snapshot, case.scenario, points=256)
    portfolio = aggregate_slices(
        "slice",
        batch.results,
        draws=batch.draws,
        exposures=batch.exposures,
        registry=registry(),
        base_currency="RUB",
        as_of=AS_OF,
        horizon=12,
        seed=20260911,
        scenario_id=batch.realisations.scenario_id,
        macro_draws_sha256=batch.realisations.macro_draws_sha256,
    )
    market = portfolio.slices["market.pnl"]
    total = np.asarray(batch.draws["SHARE-OIL", "market.pnl"]) + np.asarray(
        batch.draws["SHARE-US-TECH", "market.pnl"]
    )
    assert market.loss_quantiles.p95 == pytest.approx(np.percentile(total, 95))
    assert market.sum_of_individual_p95 > market.loss_quantiles.p95
    assert market.coverage.basis == "market_value" and market.coverage.covered_share == 1.0
    values = sum(r.metrics["equity.value_current"].value for r in batch.results)
    assert market.herfindahl < 1 and values > 0


def test_credit_and_market_slices_never_mix_in_the_mixed_portfolio():
    bundle = catalog.bundle("MULTI-ASSET")
    graph = {
        "event_id": "event",
        "nodes": [
            {"id": "event", "kind": "event", "label": "событие"},
            {"id": "demand", "kind": "channel", "label": "спрос"},
            {"id": "s", "kind": "sector", "label": "торговля", "okved": "46.63"},
            {"id": "f", "kind": "factor", "label": "выручка", "factor": "credit.revenue"},
        ],
        "edges": [
            {
                "src": a,
                "dst": b,
                "sign": 1,
                "elasticity": {"family": "point", "value": 1.0},
                "lag_months": 0,
                "evidence": [
                    {
                        "kind": "document",
                        "source_id": "t",
                        "locator": "p1",
                        "fragment_sha256": "0" * 64,
                    }
                ],
            }
            for a, b in (("event", "demand"), ("demand", "s"), ("s", "f"))
        ],
        "factor_elasticity": {},
    }
    scenario = {
        "demand": {
            "kind": "triangular",
            "low": -0.2,
            "mode": -0.1,
            "high": -0.03,
            "unit": "fraction",
            "channel": "demand",
            "factor": "credit.revenue",
        },
        "moex": {
            "kind": "triangular",
            "low": -0.3,
            "mode": -0.15,
            "high": -0.02,
            "unit": "log_return",
            "factor": "equity.market",
            "key": "MOEX",
        },
        "rub": {
            "kind": "triangular",
            "low": -0.05,
            "mode": 0.08,
            "high": 0.2,
            "unit": "log_return",
            "factor": "market.fx",
            "key": "USD/RUB",
        },
    }
    chosen = PortfolioBundle.model_validate(
        {
            **bundle.model_dump(mode="json"),
            "positions": [
                p.model_dump(mode="json")
                for p in bundle.positions
                if p.position_id in {"LOAN-MACHINERY", "SHARE-OIL", "SHARE-US-TECH"}
            ],
        }
    )
    batch = run(
        chosen,
        catalog.snapshot("SYNTHETIC-2026-09-11"),
        scenario,
        TransmissionGraph.model_validate(graph),
    )
    portfolio = aggregate_slices(
        "mixed",
        batch.results,
        draws=batch.draws,
        exposures=batch.exposures,
        registry=registry(),
        base_currency="RUB",
        as_of=AS_OF,
        horizon=12,
        seed=20260911,
        scenario_id=batch.realisations.scenario_id,
        macro_draws_sha256=batch.realisations.macro_draws_sha256,
    )
    assert set(portfolio.slices) == {"credit.loss", "market.pnl"}
    assert portfolio.slices["credit.loss"].included == ["LOAN-MACHINERY"]
    assert set(portfolio.slices["market.pnl"].included) == {"SHARE-OIL", "SHARE-US-TECH"}
    assert portfolio.slices["credit.loss"].coverage.basis == "ead"
    # One scenario set for everyone: the credit position reads the same joint matrix.
    assert {r.scenario_id for r in batch.results} == {batch.realisations.scenario_id}
