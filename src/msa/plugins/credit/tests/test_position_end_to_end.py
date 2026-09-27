"""One credit position through the editor and the platform (A13–A17, E2).

A row is typed as an analyst would type it (``msa.api.portfolio_draft.build``, the editor's
own path, turns it into a sourced instrument, position and financial-statement snapshot
item) and run as the platform runs it (``msa.engine.runner.run_batch``), on the demo
synthetic PD calibration registry so PD is calibrated rather than falling back to a score.
"""

import math
from datetime import date

import pytest

from msa.api.portfolio_draft import PortfolioDraft
from msa.api.portfolio_draft import build as build_draft
from msa.contracts.domain import contexts
from msa.contracts.evidence import Evidence
from msa.contracts.graph import (
    Edge,
    Node,
    PointDistribution,
    TransmissionGraph,
    TriangularDistribution,
)
from msa.engine.runner import run_batch
from msa.platform.registry import registry

AS_OF = date(2026, 9, 11)
AUTHOR = "test:analyst"
OKVED = "46.63"
REGISTRY = registry()

#: A healthy operating company, RUB million a year (same figures as the sanity synthetic
#: borrower): EBITDA 1800 (15 % margin), net debt 2.5x EBITDA, ICR about 2.6.
BORROWER = {
    "revenue": 12000.0,
    "cogs": 8400.0,
    "opex": 1800.0,
    "net_debt": 4500.0,
    "cash": 500.0,
    "borrowing_rate": 0.14,
    "dso": 45.0,
    "dio": 30.0,
    "dpo": 30.0,
    "tax_rate": 0.2,
    "demand_elasticity": -1.0,
    "pass_through": 0.0,
}


def loan_row(
    position_id="LOAN",
    *,
    ead=1000.0,
    lgd=0.45,
    ccf=1.0,
    import_share=0.0,
    covenants=None,
    **figures,
):
    values = {
        **BORROWER,
        **figures,
        "ead": ead,
        "lgd": lgd,
        "ccf": ccf,
        "import_share": import_share,
    }
    row = {
        "position_id": position_id,
        "name": "Заёмщик",
        "instrument_type": "corp_loan",
        "okved": OKVED,
        "currency": "RUB",
        "values": values,
    }
    if covenants:
        row["tables"] = {"covenants": covenants}
    return row


def evidence():
    return [Evidence(kind="document", source_id="S", locator="l", fragment_sha256="a" * 64)]


def edge(src, dst):
    return Edge(
        src=src,
        dst=dst,
        sign=1,
        elasticity=PointDistribution(value=1.0),
        lag_months=0,
        evidence=evidence(),
    )


def graph_to(factor_id):
    """event -> channel -> sector(``OKVED``) -> ``factor_id``: reaches the borrower above."""
    return TransmissionGraph(
        event_id="event",
        nodes=[
            Node(id="event", kind="event", label="e"),
            Node(id="channel", kind="channel", label="c"),
            Node(id="sector", kind="sector", label="s", okved=OKVED),
            Node(id="factor", kind="factor", label="f", factor=factor_id),
        ],
        edges=[edge("event", "channel"), edge("channel", "sector"), edge("sector", "factor")],
    )


NO_GRAPH = TransmissionGraph(
    event_id="event", nodes=[Node(id="event", kind="event", label="e")], edges=[]
)


def graph_to_with_channel_sector_elasticity(factor_id, elasticity):
    """Like ``graph_to`` but the channel->sector edge carries the given elasticity."""
    return TransmissionGraph(
        event_id="event",
        nodes=[
            Node(id="event", kind="event", label="e"),
            Node(id="channel", kind="channel", label="c"),
            Node(id="sector", kind="sector", label="s", okved=OKVED),
            Node(id="factor", kind="factor", label="f", factor=factor_id),
        ],
        edges=[
            edge("event", "channel"),
            Edge(
                src="channel",
                dst="sector",
                sign=1,
                elasticity=elasticity,
                lag_months=0,
                evidence=evidence(),
            ),
            edge("sector", "factor"),
        ],
    )


def shock(factor, value, channel="channel"):
    return {
        "kind": "point",
        "value": value,
        "unit": "fraction",
        "factor": factor,
        "channel": channel,
    }


def run_position(row, *, graph=NO_GRAPH, parameters=None):
    draft = PortfolioDraft(name="Портфель", base_currency="RUB", positions=[row])
    bundle, snapshot = build_draft(
        draft, author=AUTHOR, today=AS_OF, registry=REGISTRY, portfolio_id="PF-TEST"
    )
    sectors = {party.party_id: party.okved for party in bundle.parties}
    batch = run_batch(
        contexts(bundle),
        snapshot,
        parameters or {},
        graph,
        as_of=AS_OF,
        horizon=12,
        seed=7,
        registry=REGISTRY,
        sector_of=sectors.get,
        points=64,
        replicates=8,
        options=REGISTRY.run_options("demo"),
    )
    return batch.results[0]


# -- A14: an fx shock moves only import_share x costs --------------------------------------


def test_fx_shock_without_import_share_leaves_expected_loss_unchanged_and_is_flagged():
    result = run_position(
        loan_row(import_share=0.0),
        graph=graph_to("credit.fx"),
        parameters={"fx": shock("credit.fx", 0.2)},
    )
    assert result.details["credit"]["delta_expected_loss"] == 0.0
    assert "fx_without_import_share" in result.flags


def test_fx_shock_with_partial_import_share_is_between_zero_and_full_share():
    partial = run_position(
        loan_row(import_share=0.8),
        graph=graph_to("credit.fx"),
        parameters={"fx": shock("credit.fx", 0.2)},
    )
    full = run_position(
        loan_row(import_share=1.0),
        graph=graph_to("credit.fx"),
        parameters={"fx": shock("credit.fx", 0.2)},
    )
    assert partial.details["credit"]["delta_expected_loss"] > 0
    assert (
        partial.details["credit"]["delta_expected_loss"]
        < full.details["credit"]["delta_expected_loss"]
    )


# -- A13: the amount at risk is EAD x CCF ---------------------------------------------------


def test_ccf_one_half_gives_exactly_half_the_expected_loss_delta_and_ead():
    half = run_position(
        loan_row(ccf=0.5),
        graph=graph_to("credit.revenue"),
        parameters={"rev": shock("credit.revenue", -0.1)},
    )
    full = run_position(
        loan_row(ccf=1.0),
        graph=graph_to("credit.revenue"),
        parameters={"rev": shock("credit.revenue", -0.1)},
    )
    assert half.details["credit"]["expected_loss"] == pytest.approx(
        0.5 * full.details["credit"]["expected_loss"], rel=1e-9
    )
    assert half.details["credit"]["delta_expected_loss"] == pytest.approx(
        0.5 * full.details["credit"]["delta_expected_loss"], rel=1e-9
    )
    assert half.metrics["credit.ead"].value == pytest.approx(
        0.5 * full.metrics["credit.ead"].value, rel=1e-9
    )


# -- A16: an infinite ICR (gross debt zero) is the best coverage, not a missing-data cap ----


def test_zero_gross_debt_gives_the_base_pd_of_a_perfectly_covered_borrower():
    result = run_position(
        loan_row(net_debt=-BORROWER["cash"]),
        graph=graph_to("credit.revenue"),
        parameters={"rev": shock("credit.revenue", 0.0)},
    )
    expected_pd = 1.0 / (1.0 + math.exp(5.0))
    assert result.details["credit"]["pd"] == pytest.approx(expected_pd, rel=1e-9)


# -- A17: a zero-norm central scenario still calculates the covenant ------------------------


def test_zero_shock_still_calculates_the_icr_covenant_and_flags_reverse_stress_undefined():
    covenant = [{"metric": "icr", "operator": "ge", "threshold": 2.0, "test_dates": ["2027-09-11"]}]
    result = run_position(
        loan_row(covenants=covenant),
        graph=graph_to("credit.revenue"),
        parameters={"rev": shock("credit.revenue", 0.0)},
    )
    assert result.execution == "completed"
    assert result.details["covenants"]
    assert result.details["reverse_stress"] == []
    assert "reverse_stress_direction_undefined" in result.flags


# -- B10: channel->sector elasticity uncertainty widens the delta EL quantiles --------------


def test_triangular_channel_sector_elasticity_widens_delta_expected_loss_quantiles():
    result = run_position(
        loan_row(),
        graph=graph_to_with_channel_sector_elasticity(
            "credit.revenue", TriangularDistribution(low=0.5, mode=0.8, high=1.2)
        ),
        parameters={"rev": shock("credit.revenue", -0.1)},
    )
    quantiles = result.metrics["credit.delta_expected_loss"].quantiles
    assert quantiles.p05 < quantiles.p95


def test_point_channel_sector_elasticity_keeps_delta_expected_loss_quantiles_equal():
    result = run_position(
        loan_row(),
        graph=graph_to_with_channel_sector_elasticity(
            "credit.revenue", PointDistribution(value=0.8)
        ),
        parameters={"rev": shock("credit.revenue", -0.1)},
    )
    quantiles = result.metrics["credit.delta_expected_loss"].quantiles
    assert quantiles.p05 == pytest.approx(quantiles.p95, abs=1e-12)


# -- A15: EBITDA not positive in the base keeps PD at the model maximum ---------------------


def test_nonpositive_base_ebitda_flags_pd_at_model_maximum_and_leaves_the_slice():
    result = run_position(
        loan_row(opex=4000.0),
        graph=graph_to("credit.revenue"),
        parameters={"rev": shock("credit.revenue", -0.1)},
    )
    assert "pd_at_model_maximum" in result.flags
    assert result.status == "needs_review"
    assert [c.admission for c in result.contributions] == ["excluded:needs_review"]


def test_healthy_borrower_is_not_flagged_at_the_model_maximum():
    result = run_position(
        loan_row(),
        graph=graph_to("credit.revenue"),
        parameters={"rev": shock("credit.revenue", -0.1)},
    )
    assert "pd_at_model_maximum" not in result.flags


def test_project_without_an_ebitda_feature_is_calculated():
    project = {
        "credit_limit": 6000.0,
        "equity": 0.0,
        "capex_month_1_12": 100.0,
        "monthly_sales": 330.0,
        "base_rate": 0.2,
        "commissioning_month": 12.0,
        "debt": 3980.3715,
        "escrow": 1980.0,
        "sales_start_month": 1.0,
        "ead": 6000.0,
        "lgd": 0.35,
    }
    row = {**loan_row("PF"), "instrument_type": "pf_escrow", "values": project}
    result = run_position(
        row, graph=graph_to("credit.revenue"), parameters={"rev": shock("credit.revenue", -0.1)}
    )
    assert result.execution == "completed"
    assert "pd_at_model_maximum" not in result.flags


# -- E2: a rate rise reprices a fixed coupon, a floater's coupon follows the rate ----------

BOND = {"face_value": 1000.0, "coupon_rate": 0.16, "maturity_months": 36.0, "risk_free_rate": 0.14}


def bond_row(kind):
    return {**loan_row(**BOND), "instrument_type": kind}


def price_change(result):
    return result.metrics["credit.position_price_change"].quantiles.p50


def test_rate_rise_makes_a_fixed_coupon_bond_fall_more_than_a_floater():
    rate = {"rate": shock("credit.interest", 0.03)}
    fixed = run_position(bond_row("bond_fixed"), graph=graph_to("credit.interest"), parameters=rate)
    floater = run_position(
        bond_row("bond_floater"), graph=graph_to("credit.interest"), parameters=rate
    )
    assert price_change(fixed) < price_change(floater) < 0
    assert "rate_repricing" in fixed.flags
    assert "rate_repricing" in floater.flags


def test_revenue_shock_alone_does_not_reprice_a_bond_by_the_rate():
    result = run_position(
        bond_row("bond_fixed"),
        graph=graph_to("credit.revenue"),
        parameters={"rev": shock("credit.revenue", -0.1)},
    )
    assert price_change(result) < 0
    assert "rate_repricing" not in result.flags
