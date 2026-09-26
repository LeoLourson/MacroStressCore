"""Bonds of operating companies: the issuer's operating model plus the position's repricing.

The issuer's credit path comes from the operating model. The position is repriced on an
approved risk-neutral calibration when the registry has one (spec 10); otherwise on the
bond's own terms, with both readings flagged (``models.market_inputs``).
"""

import numpy as np

from ..contracts import MarketResult
from ..family import InputField as F
from ..math import bonds, market_inputs
from .corporate import OPERATING_FIELDS, OperatingCompany

MARKET_CALIBRATION_MISSING = "market_calibration_missing"

BOND_FIELDS: tuple[F, ...] = (
    F("face_value", "RUB_million", "Номинал позиции", required=True, source="terms"),
    F("coupon_rate", "fraction", "Купон", required=True, source="terms"),
    F("maturity_months", "months", "Срок до погашения", required=True, source="terms"),
    F(
        "risk_free_rate",
        "fraction",
        "Безрисковая ставка",
        required=True,
        source="market",
        market=("rate", "risk_free:{currency}", "rate"),
        hint="из рыночных данных снимка на дату оценки",
    ),
    F("coupon_frequency", "count", "Купонов в год", default=1.0, source="terms"),
    F(
        "credit_spread",
        "fraction",
        "Кредитный спред",
        hint="без него — купон минус безрисковая ставка",
        source="terms",
    ),
)


class Bond(OperatingCompany):
    types = {
        "bond_fixed": "Облигация с фиксированным купоном",
        "bond_floater": "Облигация с плавающим купоном",
    }
    model_id = "credit.bond.v3"
    fields = BOND_FIELDS + OPERATING_FIELDS
    disclosure = (*OperatingCompany.disclosure, "face_value", "coupon_rate", "maturity_months")
    decision_metrics = ("icr", "funding_gap")
    has_market = True
    review_flags = OperatingCompany.review_flags | {
        MARKET_CALIBRATION_MISSING,
        market_inputs.PROFILE_FLAG,
        market_inputs.PD_RATIO_FLAG,
    }

    def market(self, profile, inputs, registry, flags, pd):
        """Central repricing and the position value change in every realisation."""
        calibration = registry.bond_market.get(profile.asset_id)
        if calibration is not None:
            priced = bonds.reprice(
                calibration.terms,
                calibration.hazard,
                calibration.risk_free,
                calibration.basis,
                calibration.spread_change,
                flags,
            )
            return _result(priced), None
        if not registry.market_from_profile:
            _add(flags, MARKET_CALIBRATION_MISSING)
            return MarketResult(), None
        market = market_inputs.from_terms(
            face_value=inputs["face_value"],
            coupon_rate=inputs["coupon_rate"],
            maturity_months=inputs["maturity_months"],
            risk_free_rate=inputs["risk_free_rate"],
            coupon_frequency=inputs["coupon_frequency"],
            credit_spread=inputs.get("credit_spread"),
            lgd=float(profile.lgd),
        )
        if market is None:
            _add(flags, MARKET_CALIBRATION_MISSING)
            return MarketResult(), None
        _add(flags, market_inputs.PROFILE_FLAG)
        draws = None
        if pd is not None:
            base_pd, stress_pd, realised_pd = pd
            _add(flags, market_inputs.PD_RATIO_FLAG)
            change = market_inputs.spread_changes(market, base_pd, stress_pd)
            realised = market_inputs.spread_changes(market, base_pd, realised_pd)
            draws = market_inputs.position_changes(market, realised)
        else:
            _add(flags, market_inputs.NO_CHANGE_FLAG)
            change = 0.0
        priced = market_inputs.central(market, float(np.asarray(change, dtype=float)), flags)
        return _result(priced), draws


def _result(priced) -> MarketResult:
    def scalar(value):
        return float(np.asarray(value, dtype=float))

    base_price, stress_price = scalar(priced["base_price"]), scalar(priced["price"])
    return MarketResult(
        base_price=base_price,
        stress_price=stress_price,
        price_change=stress_price - base_price,
        duration=scalar(priced["duration"]),
        convexity=scalar(priced["convexity"]),
        approximation_gap=scalar(priced["gap"]),
    )


def _add(flags, flag):
    if flag not in flags:
        flags.append(flag)
