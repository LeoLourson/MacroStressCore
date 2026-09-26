"""Monthly operating and cash model (spec 5).

Everything is a trajectory: ``H`` months of flows and ``H`` end-of-month balances. Arrays
are shaped ``lead + (H,)`` so a Monte Carlo draw axis broadcasts through untouched.

The cash bridge is the load-bearing part. Interest accrues on the average debt balance,
which depends on the revolver draw, which in turn depends on the liquidity shortfall after
interest. That loop is resolved by iteration to ``cash_tolerance`` (spec 5.4) rather than
by pretending interest is known in advance.
"""

from dataclasses import dataclass, field

import numpy as np

from msa.engine.transmission import NON_NEGATIVE_DAYS, check_domain

from .calendar import Calendar

CASH_CONVERGENCE_FLAG = "cash_iteration_not_converged"
FUNDING_GAP_FLAG = "funding_gap"
SIMPLIFIED_TAX_FLAG = "simplified_tax"
NEGATIVE_COST_FLAG = "negative_cost"

DEFAULT_CASH_TOLERANCE = 1e-9
MAX_CASH_ITERATIONS = 64


@dataclass
class DebtTranche:
    """One debt tranche with its own rate build-up and schedule (spec 5.4)."""

    tranche_id: str
    opening_balance: float = 0.0
    base_rate: float | np.ndarray = 0.0
    margin: float | np.ndarray = 0.0
    stress_spread: float | np.ndarray = 0.0
    rate_floor: float | None = None
    rate_cap: float | None = None
    scheduled_draw: float | np.ndarray = 0.0
    mandatory_repay: float | np.ndarray = 0.0
    optional_repay: float | np.ndarray = 0.0
    fees: float | np.ndarray = 0.0
    revolving: bool = False
    limit: float | None = None


@dataclass
class OperatingBase:
    """Base (pre-shock) monthly trajectory of the asset."""

    revenue: float | np.ndarray
    variable_cost: float | np.ndarray
    fixed_cost: float | np.ndarray = 0.0
    opex_fixed: float | np.ndarray = 0.0
    opex_variable: float | np.ndarray = 0.0
    other_operating_income: float | np.ndarray = 0.0
    dso: float | np.ndarray = 0.0
    dio: float | np.ndarray = 0.0
    dpo: float | np.ndarray = 0.0
    other_current_assets: float | np.ndarray = 0.0
    other_current_liabilities: float | np.ndarray = 0.0
    opening_nwc: float | None = None
    maintenance_capex: float | np.ndarray = 0.0
    growth_capex: float | np.ndarray = 0.0
    other_cash_flow: float | np.ndarray = 0.0
    tax_rate: float = 0.0
    opening_cash: float = 0.0
    cash_floor: float = 0.0
    restricted_cash: float | np.ndarray = 0.0
    dividend: float | np.ndarray = 0.0
    equity_injection: float | np.ndarray = 0.0
    tranches: list[DebtTranche] = field(default_factory=list)


@dataclass
class OperatingShocks:
    """Driver changes for one scenario, in their natural economic scale."""

    price: float | np.ndarray = 0.0
    demand: float | np.ndarray = 0.0
    unit_cost: float | np.ndarray = 0.0
    fixed_cost: float | np.ndarray = 0.0
    opex_fixed: float | np.ndarray = 0.0
    opex_variable: float | np.ndarray = 0.0
    dso: float | np.ndarray = 0.0
    dio: float | np.ndarray = 0.0
    dpo: float | np.ndarray = 0.0
    capex: float | np.ndarray = 0.0
    rate: float | np.ndarray = 0.0


@dataclass
class OperatingTrajectory:
    """Monthly result. Every array is shaped ``lead + (H,)``."""

    revenue: np.ndarray
    variable_cost: np.ndarray
    fixed_cost: np.ndarray
    opex: np.ndarray
    ebitda: np.ndarray
    accounts_receivable: np.ndarray
    inventory: np.ndarray
    accounts_payable: np.ndarray
    net_working_capital: np.ndarray
    delta_nwc: np.ndarray
    cash_tax: np.ndarray
    capex: np.ndarray
    cfads: np.ndarray
    interest: np.ndarray
    draw: np.ndarray
    repay: np.ndarray
    debt: np.ndarray
    debt_by_tranche: dict[str, np.ndarray]
    cash: np.ndarray
    net_debt: np.ndarray
    funding_gap: np.ndarray
    cash_headroom: np.ndarray
    flags: list[str]


def run(
    base: OperatingBase,
    shocks: OperatingShocks,
    calendar: Calendar,
    *,
    cash_tolerance: float = DEFAULT_CASH_TOLERANCE,
    simplified_tax: bool = True,
    flags: list[str] | None = None,
) -> OperatingTrajectory:
    """Run the monthly operating and cash model for one scenario (spec 5)."""
    flags = [] if flags is None else flags
    horizon = calendar.horizon
    shape = _lead_shape(base, shocks, horizon)
    days = np.broadcast_to(calendar.day_counts(), shape)
    deltas = np.broadcast_to(calendar.deltas(), shape)

    price = _series(shocks.price, shape)
    demand = _series(shocks.demand, shape)
    unit_cost = _series(shocks.unit_cost, shape)

    # 5.1 Revenue and costs.
    revenue = _series(base.revenue, shape) * (1.0 + price) * (1.0 + demand)
    variable_cost = _series(base.variable_cost, shape) * (1.0 + unit_cost) * (1.0 + demand)
    fixed_cost = _series(base.fixed_cost, shape) * (1.0 + _series(shocks.fixed_cost, shape))
    opex = _series(base.opex_fixed, shape) * (1.0 + _series(shocks.opex_fixed, shape)) + _series(
        base.opex_variable, shape
    ) * (1.0 + demand) * (1.0 + _series(shocks.opex_variable, shape))
    if np.any(variable_cost < 0) or np.any(fixed_cost < 0) or np.any(opex < 0):
        _add(flags, NEGATIVE_COST_FLAG)
    ebitda = (
        revenue - variable_cost - fixed_cost - opex + _series(base.other_operating_income, shape)
    )

    # 5.2 Working capital on the average daily rate of the month.
    dso = _series(base.dso, shape) + _series(shocks.dso, shape)
    dio = _series(base.dio, shape) + _series(shocks.dio, shape)
    dpo = _series(base.dpo, shape) + _series(shocks.dpo, shape)
    check_domain("dso", dso, NON_NEGATIVE_DAYS, flags)
    check_domain("dio", dio, NON_NEGATIVE_DAYS, flags)
    check_domain("dpo", dpo, NON_NEGATIVE_DAYS, flags)
    accounts_receivable = revenue / days * dso
    inventory = variable_cost / days * dio
    accounts_payable = variable_cost / days * dpo
    nwc = (
        accounts_receivable
        + inventory
        + _series(base.other_current_assets, shape)
        - accounts_payable
        - _series(base.other_current_liabilities, shape)
    )
    if base.opening_nwc is None:
        base_revenue = _series(base.revenue, shape)[..., 0]
        base_variable = _series(base.variable_cost, shape)[..., 0]
        first_days = days[..., 0]
        opening_nwc = (
            base_revenue / first_days * _series(base.dso, shape)[..., 0]
            + base_variable / first_days * _series(base.dio, shape)[..., 0]
            + _series(base.other_current_assets, shape)[..., 0]
            - base_variable / first_days * _series(base.dpo, shape)[..., 0]
            - _series(base.other_current_liabilities, shape)[..., 0]
        )
    else:
        opening_nwc = base.opening_nwc
    opening_nwc = np.broadcast_to(np.asarray(opening_nwc, dtype=float), shape[:-1])
    previous_nwc = np.concatenate([opening_nwc[..., None], nwc[..., :-1]], axis=-1)
    delta_nwc = nwc - previous_nwc

    # 5.3 Cash flow available for debt service.
    if simplified_tax:
        _add(flags, SIMPLIFIED_TAX_FLAG)
    cash_tax = base.tax_rate * np.maximum(ebitda, 0.0)
    capex = (_series(base.maintenance_capex, shape) + _series(base.growth_capex, shape)) * (
        1.0 + _series(shocks.capex, shape)
    )
    cfads = ebitda - cash_tax - capex - delta_nwc + _series(base.other_cash_flow, shape)

    # 5.4 Debt, interest and the liquidity waterfall.
    rate_shock = _series(shocks.rate, shape)
    tranches = list(base.tranches)
    rates = {}
    for tranche in tranches:
        # r_kt = BaseRate + Margin + StressSpread, shocked first, then floored and capped.
        rate = (
            _series(tranche.base_rate, shape)
            + _series(tranche.margin, shape)
            + _series(tranche.stress_spread, shape)
            + rate_shock
        )
        if tranche.rate_floor is not None:
            rate = np.maximum(rate, tranche.rate_floor)
        if tranche.rate_cap is not None:
            rate = np.minimum(rate, tranche.rate_cap)
        rates[tranche.tranche_id] = rate

    dividend = _series(base.dividend, shape)
    equity_injection = _series(base.equity_injection, shape)
    scheduled = {t.tranche_id: _series(t.scheduled_draw, shape) for t in tranches}
    mandatory = {t.tranche_id: _series(t.mandatory_repay, shape) for t in tranches}
    optional = {t.tranche_id: _series(t.optional_repay, shape) for t in tranches}
    fees = {t.tranche_id: _series(t.fees, shape) for t in tranches}

    lead = shape[:-1]
    balances = {t.tranche_id: np.full(lead, float(t.opening_balance)) for t in tranches}
    debt_by_tranche = {t.tranche_id: np.zeros(shape) for t in tranches}
    interest_out = np.zeros(shape)
    draw_out = np.zeros(shape)
    repay_out = np.zeros(shape)
    cash_out = np.zeros(shape)
    gap_out = np.zeros(shape)
    cash_prev = np.full(lead, float(base.opening_cash))
    revolvers = [t for t in tranches if t.revolving]

    for index in range(horizon):
        previous = dict(balances)
        month_scheduled = {tid: scheduled[tid][..., index] for tid in scheduled}
        month_repay = {
            tid: mandatory[tid][..., index] + optional[tid][..., index] for tid in mandatory
        }
        capacity = _revolver_capacity(revolvers, previous, month_scheduled, month_repay, lead)
        delta = deltas[..., index]

        extra = np.zeros(lead)
        converged = False
        for _ in range(MAX_CASH_ITERATIONS):
            closing, interest = _close_month(
                tranches,
                previous,
                month_scheduled,
                month_repay,
                extra,
                revolvers,
                rates,
                fees,
                index,
                delta,
                lead,
            )
            total_draw = sum(month_scheduled.values()) + extra
            total_repay = sum(month_repay.values())
            cash = (
                cash_prev
                + cfads[..., index]
                - interest
                + total_draw
                - total_repay
                - dividend[..., index]
                + equity_injection[..., index]
            )
            need = np.maximum(base.cash_floor - cash, 0.0)
            candidate = np.minimum(extra + need, capacity)
            if np.all(np.abs(candidate - extra) <= cash_tolerance):
                extra = candidate
                converged = True
                break
            extra = candidate
        if not converged:
            _add(flags, CASH_CONVERGENCE_FLAG)

        closing, interest = _close_month(
            tranches,
            previous,
            month_scheduled,
            month_repay,
            extra,
            revolvers,
            rates,
            fees,
            index,
            delta,
            lead,
        )
        total_draw = sum(month_scheduled.values()) + extra
        total_repay = sum(month_repay.values())
        cash = (
            cash_prev
            + cfads[..., index]
            - interest
            + total_draw
            - total_repay
            - dividend[..., index]
            + equity_injection[..., index]
        )
        for tid, value in closing.items():
            debt_by_tranche[tid][..., index] = value
        balances = closing
        interest_out[..., index] = interest
        draw_out[..., index] = total_draw
        repay_out[..., index] = total_repay
        cash_out[..., index] = cash
        gap_out[..., index] = np.maximum(base.cash_floor - cash, 0.0)
        cash_prev = cash

    gap_out = np.where(gap_out <= max(cash_tolerance, 1e-9), 0.0, gap_out)
    if np.any(gap_out > 0):
        _add(flags, FUNDING_GAP_FLAG)
    gross_debt = sum(debt_by_tranche.values()) if debt_by_tranche else np.zeros(shape)
    # Restricted cash does not reduce net debt (spec 5.4).
    available_cash = cash_out - _series(base.restricted_cash, shape)
    return OperatingTrajectory(
        revenue=revenue,
        variable_cost=variable_cost,
        fixed_cost=fixed_cost,
        opex=opex,
        ebitda=ebitda,
        accounts_receivable=accounts_receivable,
        inventory=inventory,
        accounts_payable=accounts_payable,
        net_working_capital=nwc,
        delta_nwc=delta_nwc,
        cash_tax=cash_tax,
        capex=capex,
        cfads=cfads,
        interest=interest_out,
        draw=draw_out,
        repay=repay_out,
        debt=gross_debt,
        debt_by_tranche=debt_by_tranche,
        cash=cash_out,
        net_debt=gross_debt - available_cash,
        funding_gap=gap_out,
        cash_headroom=cash_out - base.cash_floor,
        flags=flags,
    )


def _close_month(
    tranches, previous, scheduled, repay, extra, revolvers, rates, fees, index, delta, lead
):
    """Closing balances and total interest for one month at a given revolver draw.

    ``extra`` is the discretionary revolver draw; the first revolving tranche absorbs it.
    """
    closing = {}
    for tranche in tranches:
        tid = tranche.tranche_id
        balance = previous[tid] + scheduled[tid] - repay[tid]
        if tranche.revolving and revolvers and tranche is revolvers[0]:
            balance = balance + extra
        closing[tid] = balance
    interest = np.zeros(lead)
    for tranche in tranches:
        tid = tranche.tranche_id
        average = 0.5 * (previous[tid] + closing[tid])
        interest = interest + rates[tid][..., index] * delta * average + fees[tid][..., index]
    return closing, interest


def _revolver_capacity(revolvers, previous, scheduled, repay, lead):
    if not revolvers:
        return np.zeros(lead)
    tranche = revolvers[0]
    if tranche.limit is None:
        return np.full(lead, np.inf)
    drawn = previous[tranche.tranche_id] + scheduled[tranche.tranche_id] - repay[tranche.tranche_id]
    return np.maximum(tranche.limit - drawn, 0.0)


def _series(value, shape: tuple[int, ...]) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.ndim and array.shape[-1] not in (1, shape[-1]):
        raise ValueError(f"series must end in the horizon axis of length {shape[-1]}")
    return np.broadcast_to(array, shape).astype(float, copy=False)


def _lead_shape(base: OperatingBase, shocks: OperatingShocks, horizon: int) -> tuple[int, ...]:
    leads = []
    for value in list(vars(base).values()) + list(vars(shocks).values()):
        if isinstance(value, np.ndarray) and value.ndim > 1:
            leads.append(value.shape[:-1])
        elif isinstance(value, np.ndarray) and value.ndim == 1 and value.shape[0] != horizon:
            raise ValueError(f"a one-dimensional input must have length {horizon}")
    lead = np.broadcast_shapes(*leads) if leads else ()
    return (*lead, horizon)


def _add(flags: list[str], flag: str) -> None:
    if flag not in flags:
        flags.append(flag)
