"""Quantity kinds and the addition rule (spec 2.2).

Addition is allowed only between compatible kinds. A flow may never be added to a stock
without passing through a balance equation, so ``flow_money + stock_money`` is rejected
here rather than silently producing a number. Validator V2 reports the failure.
"""

from typing import Literal

QuantityKind = Literal[
    "flow_money",
    "stock_money",
    "rate_annual",
    "relative_change",
    "log_change",
    "days",
    "probability",
    "elasticity",
]

UNIT_OF_KIND: dict[str, str] = {
    "flow_money": "RUB_million",
    "stock_money": "RUB_million",
    "rate_annual": "ratio",
    "relative_change": "fraction",
    "log_change": "ratio",
    "days": "days",
    "probability": "fraction",
    "elasticity": "ratio",
}

# Only identical kinds are additive. Money keeps flow and stock apart on purpose.
_ADDABLE: frozenset[tuple[str, str]] = frozenset((kind, kind) for kind in UNIT_OF_KIND)


class UnitMismatch(TypeError):
    """Raised when an operation mixes incompatible quantity kinds."""


def check_kind(kind: str) -> str:
    if kind not in UNIT_OF_KIND:
        raise UnitMismatch(f"unknown quantity kind: {kind!r}")
    return kind
