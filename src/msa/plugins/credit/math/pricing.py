"""Cost pass-through, price and demand (spec 4).

The cost channel and the price channel are kept apart on purpose. ``y_price`` must be the
price node signal computed from every channel *except* the pass-through of the unit cost
shock, and ``y_demand`` must exclude the demand reaction to price: both are added here
once, explicitly, so no effect is counted twice.
"""

import numpy as np

CAPACITY_FLAG = "capacity_binding"
ZERO_VOLUME_FLAG = "volume_floor_binding"
MARKET_STRUCTURE_FLAG = "market_structure_mismatch"


def price_change(unit_cost_shock, pass_through, share, price_signal=0.0) -> np.ndarray:
    """``1 + pi_t = (1 + rho_t * cshare_t * u_t) * exp(y_price_t)`` (spec 4.2).

    ``pass_through`` is the calibrated share ``rho_t`` in [0, 1]. It is a calibration
    input; deriving it from a competitor count is explicitly out of scope.
    """
    u = np.asarray(unit_cost_shock, dtype=float)
    rho = np.asarray(pass_through, dtype=float)
    share = np.asarray(share, dtype=float)
    if np.any(u <= -1.0):
        raise ValueError("unit cost shock must be greater than -1")
    if np.any((rho < 0.0) | (rho > 1.0)):
        raise ValueError("pass-through share must lie in [0, 1]")
    factor = (1.0 + rho * share * u) * np.exp(np.asarray(price_signal, dtype=float))
    if np.any(factor <= 0.0):
        raise ValueError("price factor must stay positive; pi_t must exceed -1")
    return factor - 1.0


def demand_change(price_change_value, elasticity, demand_signal=0.0) -> np.ndarray:
    """``1 + q_t = (1 + pi_t)^eps_t * exp(y_demand_t)`` (spec 4.3)."""
    pi = np.asarray(price_change_value, dtype=float)
    eps = np.asarray(elasticity, dtype=float)
    if np.any(eps >= 0.0):
        raise ValueError("price elasticity of demand must be negative")
    if np.any(pi <= -1.0):
        raise ValueError("price change must be greater than -1")
    return np.power(1.0 + pi, eps) * np.exp(np.asarray(demand_signal, dtype=float)) - 1.0


def _add(flags: list[str], flag: str) -> None:
    if flag not in flags:
        flags.append(flag)
