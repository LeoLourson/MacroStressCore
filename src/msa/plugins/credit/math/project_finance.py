"""Project finance and escrow accounts (spec 11).

Four balances are kept apart: the developer's own cash, the restricted escrow holding
buyers' money, the construction debt, and other operating cash. Escrow money is not the
project's free cash until the contractual release conditions are met, so it never reduces
net debt and never funds CAPEX before release.
"""

from dataclasses import dataclass, field

import numpy as np

LIMIT_EXCEEDED_FLAG = "construction_limit_exceeded"
FUNDING_GAP_FLAG = "project_funding_gap"


@dataclass
class ProjectBase:
    """Monthly project schedule. Arrays are length ``H`` or scalars."""

    capex: float | np.ndarray
    units_sold: float | np.ndarray = 0.0
    unit_price: float | np.ndarray = 0.0
    refunds: float | np.ndarray = 0.0
    opening_equity_cash: float = 0.0
    opening_escrow: float = 0.0
    opening_debt: float = 0.0
    opening_operating_cash: float = 0.0
    #: Equity the sponsor is contractually required to contribute before drawing debt.
    required_equity: float | np.ndarray = 0.0
    other_available_funding: float | np.ndarray = 0.0
    other_repayment_cash: float | np.ndarray = 0.0
    project_rate: float | np.ndarray = 0.0
    fees: float | np.ndarray = 0.0
    credit_limit: float | None = None
    #: 1-based month from which escrow release is contractually permitted.
    release_from_month: int | None = None
    #: Share of the available escrow balance released once permitted.
    release_share: float = 1.0
    required_payments: float | np.ndarray = 0.0


@dataclass
class ProjectTrajectory:
    sales_receipts: np.ndarray
    restricted_escrow: np.ndarray
    equity_cash: np.ndarray
    equity_use: np.ndarray
    debt_draw: np.ndarray
    construction_debt: np.ndarray
    interest: np.ndarray
    release: np.ndarray
    debt_repay: np.ndarray
    operating_cash: np.ndarray
    coverage: np.ndarray
    funding_gap: np.ndarray
    limit_excess: np.ndarray
    flags: list[str] = field(default_factory=list)


def run(base: ProjectBase, calendar, *, shocks=None, flags=None) -> ProjectTrajectory:
    """Monthly project cash waterfall (spec 11)."""
    flags = [] if flags is None else flags
    horizon = calendar.horizon
    shocks = shocks or {}
    price_shock = np.asarray(shocks.get("price", 0.0), dtype=float)
    volume_shock = np.asarray(shocks.get("volume", 0.0), dtype=float)
    capex_shock = np.asarray(shocks.get("capex", 0.0), dtype=float)
    rate_shock = np.asarray(shocks.get("rate", 0.0), dtype=float)

    shape = _shape([price_shock, volume_shock, capex_shock, rate_shock], horizon)
    lead = shape[:-1]
    deltas = np.broadcast_to(calendar.deltas(), shape)

    capex = _series(base.capex, shape) * (1.0 + capex_shock)
    units = _series(base.units_sold, shape) * (1.0 + volume_shock)
    price = _series(base.unit_price, shape) * (1.0 + price_shock)
    sales_receipts = units * price
    refunds = _series(base.refunds, shape)
    required_equity = _series(base.required_equity, shape)
    other_funding = _series(base.other_available_funding, shape)
    other_repayment = _series(base.other_repayment_cash, shape)
    rate = _series(base.project_rate, shape) + rate_shock
    fees = _series(base.fees, shape)
    required_payments = _series(base.required_payments, shape)

    escrow = np.full(lead, float(base.opening_escrow))
    equity_cash = np.full(lead, float(base.opening_equity_cash))
    debt = np.full(lead, float(base.opening_debt))
    operating_cash = np.full(lead, float(base.opening_operating_cash))

    out = {
        name: np.zeros(shape)
        for name in (
            "restricted_escrow",
            "equity_cash",
            "equity_use",
            "debt_draw",
            "construction_debt",
            "interest",
            "release",
            "debt_repay",
            "operating_cash",
            "coverage",
            "funding_gap",
        )
    }
    peak_debt = np.full(lead, -np.inf)

    for index in range(horizon):
        month = index + 1
        opening_debt = debt
        receipts = sales_receipts[..., index]
        month_refunds = refunds[..., index]

        # Equity is used first, bounded by what is available, required and actually spent.
        equity_use = np.minimum(
            np.minimum(equity_cash, required_equity[..., index]), capex[..., index]
        )
        equity_cash = equity_cash - equity_use
        capex_after_equity = np.maximum(capex[..., index] - equity_use, 0.0)
        other_funding_use = np.minimum(
            np.maximum(other_funding[..., index], 0.0), capex_after_equity
        )
        draw = np.maximum(capex_after_equity - other_funding_use, 0.0)
        if base.credit_limit is not None:
            draw = np.minimum(draw, np.maximum(base.credit_limit - opening_debt, 0.0))
        # Construction cost above the limit has no source yet: it is a funding need.
        unfunded_capex = np.maximum(capex_after_equity - other_funding_use - draw, 0.0)

        debt = opening_debt + draw
        interest = (
            rate[..., index] * deltas[..., index] * 0.5 * (opening_debt + debt) + fees[..., index]
        )
        debt = debt + interest

        # Escrow may only be released once the contractual conditions are met.
        available = escrow + receipts - month_refunds
        if base.release_from_month is not None and month >= base.release_from_month:
            release = np.minimum(base.release_share * available, available)
        else:
            release = np.zeros(lead)
        escrow = available - release

        repay = np.minimum(debt, release + other_repayment[..., index])
        debt = debt - repay
        # ``other_repayment_cash`` is a separate restricted repayment source. It
        # must not be subtracted from operating cash merely because it repays debt.
        repay_from_release = np.minimum(repay, release)
        operating_cash = operating_cash + release - repay_from_release

        # Only the part not already consumed by CAPEX remains available for other
        # required payments; counting the full amount here would use it twice.
        unused_other_funding = other_funding[..., index] - other_funding_use
        available_funding = equity_cash + operating_cash + unused_other_funding
        need = required_payments[..., index] + unfunded_capex
        gap = np.maximum(need - available_funding, 0.0)
        # Coverage is the escrow balance against the debt it is meant to repay.
        with np.errstate(divide="ignore", invalid="ignore"):
            coverage = np.where(debt > 0, escrow / np.where(debt > 0, debt, 1.0), np.inf)

        peak_debt = np.maximum(peak_debt, debt)
        for name, value in (
            ("restricted_escrow", escrow),
            ("equity_cash", equity_cash),
            ("equity_use", equity_use),
            ("debt_draw", draw),
            ("construction_debt", debt),
            ("interest", interest),
            ("release", release),
            ("debt_repay", repay),
            ("operating_cash", operating_cash),
            ("coverage", coverage),
            ("funding_gap", gap),
        ):
            out[name][..., index] = value

    limit_excess = (
        np.maximum(peak_debt - base.credit_limit, 0.0)
        if base.credit_limit is not None
        else np.zeros(lead)
    )
    if np.any(limit_excess > 0):
        _add(flags, LIMIT_EXCEEDED_FLAG)
    if np.any(out["funding_gap"] > 0):
        _add(flags, FUNDING_GAP_FLAG)
    return ProjectTrajectory(
        sales_receipts=sales_receipts, limit_excess=limit_excess, flags=flags, **out
    )


def _series(value, shape: tuple[int, ...]) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.ndim and array.shape[-1] not in (1, shape[-1]):
        raise ValueError(f"series must end in the horizon axis of length {shape[-1]}")
    return np.broadcast_to(array, shape).astype(float, copy=False)


def _shape(arrays, horizon: int) -> tuple[int, ...]:
    leads = [array.shape[:-1] for array in arrays if array.ndim > 1]
    lead = np.broadcast_shapes(*leads) if leads else ()
    return (*lead, horizon)


def _add(flags: list[str], flag: str) -> None:
    if flag not in flags:
        flags.append(flag)
