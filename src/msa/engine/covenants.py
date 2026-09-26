"""Covenant testing on the monthly trajectory (spec 9).

A covenant is breached over a *trajectory*, not on an average of per-date probabilities.
``P(breach)`` counts the realisations in which at least one check date fails after the
contractual cure mechanism has been applied.
"""

from dataclasses import dataclass, field

import numpy as np

OPERATORS = ("ge", "gt", "le", "lt")


@dataclass(frozen=True)
class CovenantDefinition:
    """The contractual test, carried verbatim rather than re-derived (spec 9)."""

    covenant_id: str
    metric: str
    operator: str
    threshold: float | np.ndarray
    #: 1-based month indices on which the covenant is tested.
    check_months: tuple[int, ...]
    cure_period_months: int = 0
    equity_cure_allowed: bool = False
    #: Contractual rounding applied to the metric before comparison.
    rounding: int | None = None
    consolidation: str = "borrower"
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.operator not in OPERATORS:
            raise ValueError(f"unknown covenant operator: {self.operator!r}")
        if not self.check_months:
            raise ValueError("a covenant needs at least one check date")
        if any(month < 1 for month in self.check_months):
            raise ValueError("check months are 1-based")
        if self.cure_period_months < 0:
            raise ValueError("a cure period cannot be negative")

    def compliant(self, metric) -> np.ndarray:
        value = np.asarray(metric, dtype=float)
        if self.rounding is not None:
            value = np.round(value, self.rounding)
        threshold = np.asarray(self.threshold, dtype=float)
        if self.operator == "ge":
            return value >= threshold
        if self.operator == "gt":
            return value > threshold
        if self.operator == "le":
            return value <= threshold
        return value < threshold

    def headroom(self, metric) -> np.ndarray:
        """Distance to the breach, positive when compliant (spec 9)."""
        value = np.asarray(metric, dtype=float)
        threshold = np.asarray(self.threshold, dtype=float)
        if self.operator in ("ge", "gt"):
            return value - threshold
        return threshold - value


def definitions(profile, calendar) -> tuple[list[CovenantDefinition], list[str]]:
    """The profile's covenants on the monthly grid, and those with no test inside the horizon.

    A covenant tested only after the horizon cannot be assessed; it does not stop the others.
    """
    tested, outside = [], []
    for covenant in profile.covenants:
        months = tuple(sorted({calendar.index_of(day) for day in covenant.test_dates} - {None}))
        if not months:
            outside.append(covenant.covenant_id)
            continue
        tested.append(
            CovenantDefinition(
                covenant_id=covenant.covenant_id,
                metric=covenant.metric,
                operator=covenant.operator,
                threshold=float(covenant.threshold),
                check_months=months,
                evidence=tuple(item.source_id for item in covenant.evidence),
            )
        )
    return tested, outside


def trajectory_breach(covenant: CovenantDefinition, metric) -> np.ndarray:
    """``B_j``: did this realisation breach at any check date, after cure? (spec 9).

    An undefined metric (NaN) at a check date cannot demonstrate compliance, so it counts
    as a breach rather than silently passing the test.
    """
    metric = np.asarray(metric, dtype=float)
    horizon = metric.shape[-1]
    compliant = covenant.compliant(metric) & np.isfinite(metric)
    breached = np.zeros(metric.shape[:-1], dtype=bool)
    for month in covenant.check_months:
        if month > horizon:
            continue
        index = month - 1
        failing = ~compliant[..., index]
        if covenant.cure_period_months:
            # A breach is cured if the metric is compliant again within the cure window.
            window = compliant[..., index + 1 : index + 1 + covenant.cure_period_months]
            if window.size:
                failing = failing & ~np.any(window, axis=-1)
        breached = breached | failing
    return breached


def breach_probability(covenant: CovenantDefinition, metric) -> float:
    """``P(breach) = (1/N) sum_j B_j`` over the draw axis (spec 9)."""
    breached = trajectory_breach(covenant, metric)
    if breached.ndim == 0:
        return float(breached)
    return float(np.mean(breached))


def worst_headroom(covenant: CovenantDefinition, metric, month_ends=None):
    """Smallest headroom across the check dates, with the month it occurs in."""
    metric = np.asarray(metric, dtype=float)
    horizon = metric.shape[-1]
    months = [month for month in covenant.check_months if month <= horizon]
    if not months:
        raise ValueError("no covenant check date falls inside the horizon")
    values = covenant.headroom(metric)
    indices = [month - 1 for month in months]
    tested = values[..., indices]
    position = int(np.argmin(np.nan_to_num(_central(tested), nan=-np.inf)))
    month = months[position]
    return {
        "headroom": tested[..., position],
        "metric": metric[..., month - 1],
        "month": month,
        "date": None if month_ends is None else month_ends[month - 1],
    }


def _central(values: np.ndarray) -> np.ndarray:
    """Collapse the draw axis so the worst check date is chosen on central values."""
    if values.ndim == 1:
        return values
    return np.mean(values, axis=tuple(range(values.ndim - 1)))
