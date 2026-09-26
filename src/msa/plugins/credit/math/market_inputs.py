"""Risk-neutral bond inputs read from the position when no market calibration is loaded.

Spec 10 prices a bond on a market-calibrated risk-neutral intensity. A position without an
approved calibration still carries its contractual terms, so the stand reads them directly.
Two readings are assumptions rather than market data; both are flagged, which sends the
result to review:

- the credit spread is ``credit_spread`` from the profile or, failing that, the coupon over
  the risk-free rate of a bond issued at par (``market_inputs_from_profile``);
- the scenario moves the spread in proportion to the stressed PD over the base PD
  (``spread_scaled_by_pd_ratio``). Without a calibrated PD there is no ratio to use, and the
  spread stays put (``spread_change_unavailable``).
"""

from dataclasses import dataclass

import numpy as np

from .bonds import BondTerms, price, reprice

PROFILE_FLAG = "market_inputs_from_profile"
PD_RATIO_FLAG = "spread_scaled_by_pd_ratio"
NO_CHANGE_FLAG = "spread_change_unavailable"


@dataclass(frozen=True)
class ProfileMarket:
    terms: BondTerms
    hazard: np.ndarray
    risk_free: np.ndarray
    spread: float
    face_value: float


def from_terms(
    *,
    face_value: float,
    coupon_rate: float,
    maturity_months: float,
    risk_free_rate: float,
    coupon_frequency: float,
    credit_spread: float | None,
    lgd: float,
) -> ProfileMarket | None:
    """Terms of a bond issued at par; ``None`` when they define no positive credit spread."""
    if maturity_months < 1:
        return None
    spread = coupon_rate - risk_free_rate if credit_spread is None else credit_spread
    if spread <= 0 or lgd <= 0:
        return None
    frequency = max(1, int(coupon_frequency))
    step = 12 / frequency
    months = np.arange(step, maturity_months + 1e-9, step)
    if months.size == 0 or months[-1] < maturity_months:
        months = np.append(months, maturity_months)
    times = months / 12.0
    flows = np.full(times.size, coupon_rate * 100.0 / frequency)
    flows[-1] += 100.0
    # A defaulted bond recovers 1 - LGD of face; the intensity pays the spread over that loss.
    hazard = np.full(times.size, spread / lgd)
    risk_free = np.full(times.size, np.log1p(risk_free_rate))
    return ProfileMarket(
        terms=BondTerms(times=times, flows=flows, recovery=100.0 * (1.0 - lgd)),
        hazard=hazard,
        risk_free=risk_free,
        spread=float(spread),
        face_value=face_value,
    )


def spread_changes(market: ProfileMarket, base_pd, stressed_pd):
    """``ds = s * (PD_stress / PD_base - 1)``, elementwise over scenario realisations."""
    base = float(np.asarray(base_pd, dtype=float))
    stressed = np.asarray(stressed_pd, dtype=float)
    return market.spread * (stressed / base - 1.0)


def central(market: ProfileMarket, spread_change: float, flags: list[str]):
    return reprice(market.terms, market.hazard, market.risk_free, 0.0, spread_change, flags)


def position_changes(market: ProfileMarket, spread_change):
    """Change of the position value in money for each realisation's spread change."""
    base = float(price(market.terms, market.hazard, market.risk_free))
    shift = np.asarray(spread_change, dtype=float)[..., None]
    stressed = price(market.terms, market.hazard, market.risk_free, shift)
    return (stressed - base) / 100.0 * market.face_value
