"""Raw financial metrics (spec 5.5).

Metrics are stored untruncated. Where a ratio has no meaning — a non-positive denominator
— the value is ``undefined`` (NaN paired with a mask) rather than a cap. Capping belongs to
PD feature engineering (spec 7.2) and a capped feature is never shown as the actual ratio.
"""

from dataclasses import dataclass

import numpy as np

EBITDA_NONPOSITIVE_FLAG = "ebitda_nonpositive"
INTEREST_NONPOSITIVE_FLAG = "cash_interest_nonpositive"
LTM_ANNUALISED_FLAG = "ltm_annualised"
CAPITAL_NONPOSITIVE_FLAG = "capital_nonpositive"


@dataclass(frozen=True)
class RawMetric:
    """A metric trajectory with an explicit definedness mask."""

    value: np.ndarray
    defined: np.ndarray

    def masked(self) -> np.ndarray:
        """NaN wherever the metric is undefined."""
        return np.where(self.defined, self.value, np.nan)


def trailing_sum(series, prior=None, window: int = 12, flags: list[str] | None = None):
    """Rolling ``window``-month sum ending in each month.

    With ``prior`` (the ``window - 1`` months preceding the horizon) the sum is a true LTM
    from month one. Without it the horizon-to-date sum is scaled to a full window and
    ``ltm_annualised`` is raised, because the early months are not a full year.
    """
    series = np.asarray(series, dtype=float)
    horizon = series.shape[-1]
    if prior is None:
        cumulative = np.cumsum(series, axis=-1)
        months = np.arange(1, horizon + 1, dtype=float)
        if horizon < window and flags is not None:
            _add(flags, LTM_ANNUALISED_FLAG)
        scaled = cumulative * (window / months)
        full = months >= window
        if flags is not None and not bool(np.all(full)):
            _add(flags, LTM_ANNUALISED_FLAG)
        # Months that already cover the full window use the true rolling sum.
        rolling = np.where(full, _rolling(series, window), scaled)
        return rolling
    prior = np.broadcast_to(np.asarray(prior, dtype=float), series.shape[:-1] + (window - 1,))
    extended = np.concatenate([prior, series], axis=-1)
    return _rolling(extended, window)[..., -horizon:]


def raw_icr(ltm_ebitda, ltm_cash_interest, flags: list[str] | None = None) -> RawMetric:
    """``ICR_raw = LTM EBITDA / LTM CashInterest`` where the denominator is positive."""
    ebitda = np.asarray(ltm_ebitda, dtype=float)
    interest = np.asarray(ltm_cash_interest, dtype=float)
    defined = interest > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        value = np.where(defined, ebitda / np.where(defined, interest, 1.0), np.nan)
    if flags is not None and not bool(np.all(defined)):
        _add(flags, INTEREST_NONPOSITIVE_FLAG)
    return RawMetric(value=value, defined=defined)


def raw_leverage(net_debt, ltm_ebitda, flags: list[str] | None = None) -> RawMetric:
    """``Leverage_raw = NetDebt / LTM EBITDA`` only where LTM EBITDA is positive."""
    net_debt = np.asarray(net_debt, dtype=float)
    ebitda = np.asarray(ltm_ebitda, dtype=float)
    defined = ebitda > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        value = np.where(defined, net_debt / np.where(defined, ebitda, 1.0), np.nan)
    if flags is not None and not bool(np.all(defined)):
        _add(flags, EBITDA_NONPOSITIVE_FLAG)
    return RawMetric(value=value, defined=defined)


def raw_debt_to_equity(debt, equity, flags: list[str] | None = None) -> RawMetric:
    """Undefined at non-positive equity; a capital shortfall indicator is raised instead."""
    debt = np.asarray(debt, dtype=float)
    equity = np.asarray(equity, dtype=float)
    defined = equity > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        value = np.where(defined, debt / np.where(defined, equity, 1.0), np.nan)
    if flags is not None and not bool(np.all(defined)):
        _add(flags, CAPITAL_NONPOSITIVE_FLAG)
    return RawMetric(value=value, defined=defined)


def _rolling(series: np.ndarray, window: int) -> np.ndarray:
    cumulative = np.cumsum(series, axis=-1)
    shifted = np.concatenate(
        [np.zeros(series.shape[:-1] + (window,)), cumulative[..., :-window]], axis=-1
    )
    return cumulative - shifted


def _add(flags: list[str], flag: str) -> None:
    if flag not in flags:
        flags.append(flag)
