"""Bond pricing with default and recovery (spec 10).

Pricing uses a risk-neutral hazard curve calibrated to the market, not a physical PD
multiplied by a constant. Sensitivities come from numerical shifts of the curve whose risk
is being measured, and a large shock re-prices the bond in full instead of extrapolating a
local approximation.
"""

from dataclasses import dataclass

import numpy as np

APPROXIMATION_FLAG = "duration_approximation_gap"
#: Beyond this spread move the local expansion is not used (spec 10.2).
SMALL_SHIFT = 0.01
DEFAULT_BUMP = 1e-4


@dataclass
class BondTerms:
    """Promised cash flows on the monthly grid plus the recovery assumption."""

    #: Payment times in years from the valuation date.
    times: np.ndarray
    #: Promised cash flow at each time, per 100 of face.
    flows: np.ndarray
    #: Recovery paid if default happens in that period, per 100 of face.
    recovery: float | np.ndarray = 40.0
    #: Year fraction of each period, used for the hazard integral.
    deltas: np.ndarray | None = None

    def period_deltas(self) -> np.ndarray:
        if self.deltas is not None:
            return np.asarray(self.deltas, dtype=float)
        times = np.asarray(self.times, dtype=float)
        return np.diff(times, prepend=0.0)


def risk_neutral_survival(hazard, deltas) -> np.ndarray:
    """``S^Q_t = exp(-sum_{k<=t} h^Q_k delta_k)`` (spec 10.1)."""
    hazard = np.asarray(hazard, dtype=float)
    deltas = np.broadcast_to(np.asarray(deltas, dtype=float), hazard.shape)
    if np.any(hazard < 0):
        raise ValueError("the risk-neutral hazard must be non-negative")
    return np.exp(-np.cumsum(hazard * deltas, axis=-1))


def risk_neutral_default(hazard, deltas) -> np.ndarray:
    """``q^Q_t = S^Q_{t-1} (1 - exp(-h^Q_t delta_t))``."""
    hazard = np.asarray(hazard, dtype=float)
    deltas = np.broadcast_to(np.asarray(deltas, dtype=float), hazard.shape)
    alive = risk_neutral_survival(hazard, deltas)
    previous = np.concatenate([np.ones(alive.shape[:-1] + (1,)), alive[..., :-1]], axis=-1)
    return previous * (-np.expm1(-hazard * deltas))


def price(terms: BondTerms, hazard, risk_free, basis=0.0, recovery_times=None) -> np.ndarray:
    """``P = sum_t S^Q_t CF_t DF_t + sum_t q^Q_t Rec_t DF_tau`` (spec 10.1).

    ``risk_free`` is the continuously compounded zero rate ``z`` and ``basis`` the separately
    calibrated liquidity or other spread ``l``.
    """
    times = np.asarray(terms.times, dtype=float)
    flows = np.asarray(terms.flows, dtype=float)
    deltas = terms.period_deltas()
    rate = np.asarray(risk_free, dtype=float) + np.asarray(basis, dtype=float)
    if rate.ndim and rate.shape[-1] not in (1, times.size):
        raise ValueError("a rate curve must end in the bond cash-flow axis")

    alive = risk_neutral_survival(hazard, deltas)
    default = risk_neutral_default(hazard, deltas)
    discount = np.exp(-rate * times)
    # Recovery is paid at the expected settlement time, not at the coupon date.
    tau = times if recovery_times is None else np.asarray(recovery_times, dtype=float)
    recovery_discount = np.exp(-rate * tau)
    promised = np.sum(alive * flows * discount, axis=-1)
    recovered = np.sum(default * np.asarray(terms.recovery, dtype=float) * recovery_discount, -1)
    return promised + recovered


def duration_convexity(terms: BondTerms, hazard, risk_free, basis=0.0, bump=DEFAULT_BUMP):
    """Numerical spread duration and convexity by central differences (spec 10.2)."""
    base = price(terms, hazard, risk_free, basis)
    up = price(terms, hazard, risk_free, np.asarray(basis, dtype=float) + bump)
    down = price(terms, hazard, risk_free, np.asarray(basis, dtype=float) - bump)
    duration = -(up - down) / (2.0 * bump * base)
    convexity = (up - 2.0 * base + down) / (bump**2 * base)
    return base, duration, convexity


def local_price_change(price_value, duration, convexity, spread_change) -> np.ndarray:
    """``dP ~ P(-D ds + C ds^2 / 2)``; valid for small shifts only (spec 10.2)."""
    ds = np.asarray(spread_change, dtype=float)
    return np.asarray(price_value, dtype=float) * (
        -np.asarray(duration, dtype=float) * ds + 0.5 * np.asarray(convexity, dtype=float) * ds**2
    )


def reprice(
    terms: BondTerms, hazard, risk_free, basis, spread_change, flags: list[str] | None = None
):
    """Full reprice, with the local approximation reported alongside for comparison.

    A large shift is repriced in full; the gap between the two is surfaced rather than
    hidden, because the approximation is only licensed near zero.
    """
    ds = np.asarray(spread_change, dtype=float)
    base, duration, convexity = duration_convexity(terms, hazard, risk_free, basis)
    full = price(terms, hazard, risk_free, np.asarray(basis, dtype=float) + ds)
    approximate = base + local_price_change(base, duration, convexity, ds)
    if flags is not None and np.any(np.abs(ds) > SMALL_SHIFT):
        _add(flags, APPROXIMATION_FLAG)
    return {
        "base_price": base,
        "price": full,
        "approximate_price": approximate,
        "duration": duration,
        "convexity": convexity,
        "gap": full - approximate,
    }


def _add(flags: list[str], flag: str) -> None:
    if flag not in flags:
        flags.append(flag)
