"""Leasing company model (spec 12).

Portfolio roll-forward in money, finance income on the average net investment, and a
lessee PD transferred on the logit scale. A loss reduces equity; where equity turns
non-positive the debt-to-equity ratio is not computed at all.
"""

from dataclasses import dataclass, field

import numpy as np

from msa.engine.metrics import CAPITAL_NONPOSITIVE_FLAG


@dataclass
class LeasingBase:
    """Monthly leasing book. Arrays are length ``H`` or scalars."""

    opening_nil: float
    scheduled_principal: float | np.ndarray = 0.0
    prepayment: float | np.ndarray = 0.0
    writeoff: float | np.ndarray = 0.0
    new_business: float | np.ndarray = 0.0
    advance_rate: float | np.ndarray = 0.0
    portfolio_yield: float | np.ndarray = 0.0
    fee_income: float | np.ndarray = 0.0
    opex: float | np.ndarray = 0.0
    opening_debt: float = 0.0
    funding_rate: float | np.ndarray = 0.0
    fees: float | np.ndarray = 0.0
    debt_amortisation: float | np.ndarray = 0.0
    opening_equity: float = 0.0
    opening_ecl: float = 0.0
    tax_rate: float = 0.0
    dividend: float | np.ndarray = 0.0
    equity_injection: float | np.ndarray = 0.0
    other_comprehensive_income: float | np.ndarray = 0.0
    other_non_operating: float | np.ndarray = 0.0
    recovery_of_writeoff: float | np.ndarray = 0.0


@dataclass
class LeasingTrajectory:
    net_investment: np.ndarray
    average_net_investment: np.ndarray
    finance_income: np.ndarray
    funding_cost: np.ndarray
    ppop: np.ndarray
    credit_loss_expense: np.ndarray
    profit_before_tax: np.ndarray
    net_income: np.ndarray
    equity: np.ndarray
    debt: np.ndarray
    ecl: np.ndarray
    flags: list[str] = field(default_factory=list)


def run(base: LeasingBase, calendar, *, shocks=None, flags=None) -> LeasingTrajectory:
    """Monthly leasing roll-forward, income and capital (spec 12)."""
    flags = [] if flags is None else flags
    horizon = calendar.horizon
    shocks = shocks or {}
    volume_shock = np.asarray(shocks.get("new_business", 0.0), dtype=float)
    yield_shock = np.asarray(shocks.get("yield", 0.0), dtype=float)
    funding_shock = np.asarray(shocks.get("funding_rate", 0.0), dtype=float)
    opex_shock = np.asarray(shocks.get("opex", 0.0), dtype=float)
    #: Expected credit loss on the book, supplied by the credit module per month.
    ecl_path = shocks.get("ecl")

    shape = _shape([volume_shock, yield_shock, funding_shock, opex_shock], horizon)
    lead = shape[:-1]
    deltas = np.broadcast_to(calendar.deltas(), shape)

    scheduled = _series(base.scheduled_principal, shape)
    prepayment = _series(base.prepayment, shape)
    writeoff = _series(base.writeoff, shape)
    new_business = _series(base.new_business, shape) * (1.0 + volume_shock)
    advance = _series(base.advance_rate, shape)
    book_yield = _series(base.portfolio_yield, shape) + yield_shock
    fee_income = _series(base.fee_income, shape)
    opex = _series(base.opex, shape) * (1.0 + opex_shock)
    funding_rate = _series(base.funding_rate, shape) + funding_shock
    fees = _series(base.fees, shape)
    amortisation = _series(base.debt_amortisation, shape)
    dividend = _series(base.dividend, shape)
    injection = _series(base.equity_injection, shape)
    oci = _series(base.other_comprehensive_income, shape)
    other = _series(base.other_non_operating, shape)
    recovered = _series(base.recovery_of_writeoff, shape)
    ecl_series = None if ecl_path is None else _series(ecl_path, shape)

    nil = np.full(lead, float(base.opening_nil))
    debt = np.full(lead, float(base.opening_debt))
    equity = np.full(lead, float(base.opening_equity))
    ecl = np.full(lead, float(base.opening_ecl))

    out = {
        name: np.zeros(shape)
        for name in (
            "net_investment",
            "average_net_investment",
            "finance_income",
            "funding_cost",
            "ppop",
            "credit_loss_expense",
            "profit_before_tax",
            "net_income",
            "equity",
            "debt",
            "ecl",
        )
    }

    for index in range(horizon):
        opening_nil, opening_debt, opening_ecl = nil, debt, ecl
        nil = (
            opening_nil
            - scheduled[..., index]
            - prepayment[..., index]
            - writeoff[..., index]
            + new_business[..., index] * (1.0 - advance[..., index])
        )
        average = 0.5 * (opening_nil + nil)
        finance_income = book_yield[..., index] * deltas[..., index] * average

        debt = opening_debt - amortisation[..., index]
        funding_cost = (
            funding_rate[..., index] * deltas[..., index] * 0.5 * (opening_debt + debt)
            + fees[..., index]
        )
        ppop = finance_income + fee_income[..., index] - opex[..., index] - funding_cost
        ecl = opening_ecl if ecl_series is None else ecl_series[..., index]
        credit_loss = ecl - opening_ecl + writeoff[..., index] - recovered[..., index]
        pbt = ppop - credit_loss + other[..., index]
        tax = base.tax_rate * np.maximum(pbt, 0.0)
        net_income = pbt - tax
        # A loss reduces equity (spec 22).
        equity = (
            equity + net_income - dividend[..., index] + injection[..., index] + oci[..., index]
        )
        for name, value in (
            ("net_investment", nil),
            ("average_net_investment", average),
            ("finance_income", finance_income),
            ("funding_cost", funding_cost),
            ("ppop", ppop),
            ("credit_loss_expense", credit_loss),
            ("profit_before_tax", pbt),
            ("net_income", net_income),
            ("equity", equity),
            ("debt", debt),
            ("ecl", ecl),
        ):
            out[name][..., index] = value

    if np.any(out["equity"] <= 0):
        _add(flags, CAPITAL_NONPOSITIVE_FLAG)
    return LeasingTrajectory(flags=flags, **out)


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
