"""Calendar and day counts (spec 2.1).

Flows belong to month ``t``; balances are end-of-month ``t``. Month ``1`` is the first
full calendar month that starts after ``as_of``.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date

import numpy as np

DAY_COUNT = 365.0
DEFAULT_HORIZON = 12


def add_months(day: date, months: int) -> date:
    offset = day.year * 12 + day.month - 1 + months
    year, month = divmod(offset, 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


@dataclass(frozen=True)
class Calendar:
    """Monthly grid of ``horizon`` months anchored on ``as_of``."""

    as_of: date
    horizon: int = DEFAULT_HORIZON

    def __post_init__(self):
        if self.horizon < 1:
            raise ValueError("horizon must be at least one month")

    def _check(self, t: int) -> None:
        if not 1 <= t <= self.horizon:
            raise IndexError(f"month {t} is outside the horizon 1..{self.horizon}")

    def month_start(self, t: int) -> date:
        self._check(t)
        first_full = add_months(date(self.as_of.year, self.as_of.month, 1), 1)
        return add_months(first_full, t - 1)

    def month_end(self, t: int) -> date:
        start = self.month_start(t)
        return date(start.year, start.month, monthrange(start.year, start.month)[1])

    def days(self, t: int) -> int:
        start = self.month_start(t)
        return monthrange(start.year, start.month)[1]

    def delta(self, t: int) -> float:
        """Year fraction of month ``t``: days_t / 365."""
        return self.days(t) / DAY_COUNT

    def deltas(self) -> np.ndarray:
        return np.array([self.delta(t) for t in self.months()], dtype=float)

    def day_counts(self) -> np.ndarray:
        return np.array([self.days(t) for t in self.months()], dtype=float)

    def months(self) -> range:
        return range(1, self.horizon + 1)

    def month_ends(self) -> list[date]:
        return [self.month_end(t) for t in self.months()]

    def index_of(self, day: date) -> int | None:
        """1-based month index containing ``day``, or None when outside the horizon."""
        for t in self.months():
            if self.month_start(t) <= day <= self.month_end(t):
                return t
        return None

    def discount_factors(self, annual_rate) -> np.ndarray:
        """DF_t = exp(-sum_{k<=t} r_k * delta_k) on the month-end grid."""
        rate = np.broadcast_to(np.asarray(annual_rate, dtype=float), (self.horizon,))
        return np.exp(-np.cumsum(rate * self.deltas()))
