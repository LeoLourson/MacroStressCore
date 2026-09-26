"""Exchange rates: an instrument's currency against the portfolio's base currency.

A position in another currency is valued at the spot rate of the snapshot and moved by the
``market.fx`` factor of its currency pair. The pair is written ``<CCY>/<BASE>`` and its
rate is the price of one unit of ``CCY`` in ``BASE`` (``USD/RUB`` 92.5). A missing rate is
an error of the position, never a silent 1.
"""

import numpy as np

from msa.contracts.snapshot import FX_RATE
from msa.plugin_sdk.model import DataRequirement, FactorRequirement

FX_FACTOR = "market.fx"
FX_KEY = "fx"


def pair(currency: str, base: str) -> str:
    return f"{currency}/{base}"


def requirement(currency: str, base: str) -> DataRequirement | None:
    if currency == base:
        return None
    return DataRequirement(
        key=FX_KEY,
        kind=FX_RATE,
        subject=pair(currency, base),
        purpose=f"курс {currency} к {base} на дату оценки",
    )


def factor(currency: str, base: str) -> FactorRequirement | None:
    if currency == base:
        return None
    return FactorRequirement(factor_id=FX_FACTOR, key=pair(currency, base))


def spot(prepared, currency: str, base: str) -> float | None:
    """The spot rate of the snapshot; ``None`` when absent. 1 for the base currency."""
    if currency == base:
        return 1.0
    item = prepared.item(FX_KEY)
    if item is None or "rate" not in item.values:
        return None
    return float(item.values["rate"].value)


def log_change(scenario, currency: str, base: str, flags: list[str]):
    """``(central, draws)`` of the pair's log change; zero for the base currency.

    A pair the scenario does not move is unshocked, and the result says so.
    """
    shape = (scenario.replicates, scenario.points)
    if currency == base:
        return 0.0, np.zeros(shape)
    names = scenario.parameters_for(FX_FACTOR, pair(currency, base))
    if not names:
        flag = f"factor_not_in_scenario:{FX_FACTOR}:{pair(currency, base)}"
        if flag not in flags:
            flags.append(flag)
        return 0.0, np.zeros(shape)
    central = sum(scenario.central(name) for name in names)
    draws = np.sum([scenario.draws(name) for name in names], axis=0)
    return float(central), np.asarray(draws, dtype=float)
