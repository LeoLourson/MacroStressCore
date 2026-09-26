"""Result statuses (spec 19).

The five statuses are ordered by how much they restrict use of the number. ``worst``
combines statuses reached along a calculation: a result is only as usable as its least
usable part.
"""

from typing import Literal

ResultStatus = Literal["ok", "uncalibrated", "needs_review", "incomplete", "invalid"]

# Increasing restriction. "uncalibrated" is not a data problem: the arithmetic is sound
# but the probabilistic output may not be read as PD.
SEVERITY: dict[str, int] = {
    "ok": 0,
    "uncalibrated": 1,
    "needs_review": 2,
    "incomplete": 3,
    "invalid": 4,
}

#: Statuses whose numbers must not enter portfolio aggregation without disclosure.
EXCLUDED_FROM_AGGREGATION: frozenset[str] = frozenset({"invalid"})


def worst(*statuses: str) -> ResultStatus:
    known = [status for status in statuses if status]
    for status in known:
        if status not in SEVERITY:
            raise ValueError(f"unknown result status: {status!r}")
    if not known:
        return "ok"
    return max(known, key=lambda status: SEVERITY[status])  # type: ignore[return-value]
