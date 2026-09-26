"""Reverse stress testing along an explicit direction (spec 15).

The stress path ``x(lambda) = x_0 + lambda * d`` is part of the answer, not an implicit
assumption: the direction, its norm and the plausibility bounds are reported alongside
``lambda*``.

Where the metric jumps across the threshold the result is the bracketing interval, not a
root that the function never actually takes. Where the metric is not monotone the first
crossing is returned together with every later one, and none of them is called a global
minimum.
"""

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq

NON_MONOTONIC_FLAG = "non_monotonic"
DISCONTINUOUS_FLAG = "discontinuous_boundary"

DEFAULT_LAMBDA_MAX = 5.0
DEFAULT_GRID = 64
#: A jump larger than this share of the metric range is treated as a discontinuity.
JUMP_SHARE = 0.25


@dataclass(frozen=True)
class Direction:
    """The explicit stress direction and its plausibility bounds (spec 15)."""

    components: dict[str, float]
    lambda_max: float = DEFAULT_LAMBDA_MAX
    #: Free-text record of what makes this direction plausible.
    plausibility: str = ""

    def norm(self) -> float:
        return float(np.linalg.norm(list(self.components.values())))

    def at(self, lam: float) -> dict[str, float]:
        return {name: value * lam for name, value in self.components.items()}


@dataclass
class ReverseStressResult:
    status: str
    lambda_star: float | None
    #: Bracketing interval when the boundary is a jump rather than a root.
    interval: tuple[float, float] | None
    direction: Direction
    shock: dict[str, float] | None
    metric_before: float | None
    metric_after: float | None
    continuous: bool
    later_crossings: list[tuple[float, float]] = field(default_factory=list)
    flags: tuple[str, ...] = ()


def _breached(value, threshold, operator) -> bool:
    if not np.isfinite(value):
        return True
    if operator in ("ge", "gt"):
        return value < threshold if operator == "ge" else value <= threshold
    return value > threshold if operator == "le" else value >= threshold


def search(
    metric,
    threshold: float,
    operator: str,
    direction: Direction,
    *,
    grid: int = DEFAULT_GRID,
) -> ReverseStressResult:
    """Smallest ``lambda`` along ``direction`` that pushes the metric across ``threshold``.

    ``metric`` maps a scalar ``lambda`` to the metric value.
    """
    flags: list[str] = []
    start = float(metric(0.0))
    if _breached(start, threshold, operator):
        return ReverseStressResult(
            status="already_breached",
            lambda_star=0.0,
            interval=None,
            direction=direction,
            shock=direction.at(0.0),
            metric_before=start,
            metric_after=start,
            continuous=True,
        )

    lambdas = np.linspace(0.0, direction.lambda_max, grid + 1)
    values = np.array([float(metric(float(lam))) for lam in lambdas])
    breaches = np.array([_breached(value, threshold, operator) for value in values])

    crossings = [
        (float(lambdas[i]), float(lambdas[i + 1]))
        for i in range(len(lambdas) - 1)
        if not breaches[i] and breaches[i + 1]
    ]
    if not crossings:
        return ReverseStressResult(
            status="not_breached",
            lambda_star=None,
            interval=None,
            direction=direction,
            shock=None,
            metric_before=start,
            metric_after=float(values[-1]),
            continuous=True,
        )

    if not _monotone(values, operator):
        flags.append(NON_MONOTONIC_FLAG)

    low, high = crossings[0]
    finite = values[np.isfinite(values)]
    span = float(np.ptp(finite)) if finite.size else 0.0
    index = int(np.searchsorted(lambdas, low, side="left"))
    jump = abs(values[index + 1] - values[index])
    continuous = span == 0.0 or jump <= JUMP_SHARE * span

    if continuous:
        try:
            root = float(brentq(lambda lam: float(metric(lam)) - threshold, low, high, xtol=1e-10))
        except ValueError:
            # The sign condition Brent needs does not hold: report the bracket instead.
            continuous = False
            root = None
    else:
        root = None

    if not continuous:
        flags.append(DISCONTINUOUS_FLAG)
    return ReverseStressResult(
        status="found",
        lambda_star=root,
        interval=None if continuous else (low, high),
        direction=direction,
        shock=direction.at(root if root is not None else high),
        metric_before=float(values[index]),
        metric_after=float(values[index + 1]),
        continuous=continuous,
        later_crossings=crossings[1:],
        flags=tuple(flags),
    )


def _monotone(values: np.ndarray, operator: str, tolerance: float = 1e-12) -> bool:
    finite = values[np.isfinite(values)]
    if finite.size < 2:
        return True
    steps = np.diff(finite)
    if operator in ("ge", "gt"):
        return bool(np.all(steps <= tolerance))
    return bool(np.all(steps >= -tolerance))
