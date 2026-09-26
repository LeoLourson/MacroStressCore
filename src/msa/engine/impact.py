"""Impact presented along separate risk axes (spec 17).

Risk is not collapsed into one number. Each axis carries its own measures, and the business
band comes from versioned rules of a specific process — a threshold is not probabilistically
significant until it has been calibrated, and the rule that fires says why and what to do.
"""

from dataclasses import dataclass, field
from typing import Literal

Axis = Literal["credit", "market", "liquidity", "covenant", "data_and_model"]
#: ``not_assessed``: no approved rule measured the axis. It is never shown as a low risk.
Band = Literal["not_assessed", "low", "medium", "high", "critical"]

AXES: tuple[Axis, ...] = ("credit", "market", "liquidity", "covenant", "data_and_model")


@dataclass
class AxisResult:
    axis: Axis
    measures: dict[str, float | None]
    band: Band = "not_assessed"
    #: Why the band fired and what the analyst should do about it.
    reason: str = ""
    recommendation: str = ""
    flags: list[str] = field(default_factory=list)


@dataclass
class ThresholdRule:
    """A versioned banding rule owned by a process, not by the model (spec 17)."""

    rule_id: str
    version: str
    axis: Axis
    measure: str
    #: Ascending cut-offs for medium, high and critical.
    cutoffs: tuple[float, float, float]
    reason: str
    recommendation: str
    #: False until the threshold has been calibrated; bands stay indicative until then.
    calibrated: bool = False

    def band(self, value: float | None) -> Band:
        if value is None:
            return "not_assessed"
        medium, high, critical = self.cutoffs
        if value >= critical:
            return "critical"
        if value >= high:
            return "high"
        if value >= medium:
            return "medium"
        return "low"


def apply_rules(results: list[AxisResult], rules: list[ThresholdRule]) -> list[AxisResult]:
    """Band each axis by its rules, keeping the strongest trigger and its explanation."""
    order = {"not_assessed": -1, "low": 0, "medium": 1, "high": 2, "critical": 3}
    for result in results:
        for rule in rules:
            if rule.axis != result.axis or rule.measure not in result.measures:
                continue
            band = rule.band(result.measures[rule.measure])
            if order[band] > order[result.band]:
                result.band = band
                if band != "low":
                    result.reason = rule.reason
                    result.recommendation = rule.recommendation
            if not rule.calibrated and order[band] > order["low"]:
                flag = f"uncalibrated_threshold:{rule.rule_id}"
                if flag not in result.flags:
                    result.flags.append(flag)
    return results


def credit_axis(
    *, pd=None, risk_score=None, lgd=None, ead=None, expected_loss=None, delta_expected_loss=None
) -> AxisResult:
    return AxisResult(
        axis="credit",
        measures={
            "pd": pd,
            "risk_score": risk_score,
            "lgd": lgd,
            "ead": ead,
            "expected_loss": expected_loss,
            "delta_expected_loss": delta_expected_loss,
        },
    )


def market_axis(*, price=None, price_change=None, duration=None, convexity=None) -> AxisResult:
    return AxisResult(
        axis="market",
        measures={
            "price": price,
            "price_change": price_change,
            "duration": duration,
            "convexity": convexity,
        },
    )


def liquidity_axis(*, cash_headroom=None, funding_gap=None, limit_excess=None) -> AxisResult:
    return AxisResult(
        axis="liquidity",
        measures={
            "min_cash_headroom": cash_headroom,
            "funding_gap": funding_gap,
            "limit_excess": limit_excess,
        },
    )


def covenant_axis(*, headroom=None, breach_probability=None, breach_month=None) -> AxisResult:
    return AxisResult(
        axis="covenant",
        measures={
            "min_headroom": headroom,
            "breach_probability": breach_probability,
            "breach_month": breach_month,
        },
    )


def data_and_model_axis(
    *, data_quality=None, stale_days=None, numerical_halfwidth=None, calibrated=None
) -> AxisResult:
    return AxisResult(
        axis="data_and_model",
        measures={
            "data_quality": data_quality,
            "stale_days": stale_days,
            "numerical_halfwidth": numerical_halfwidth,
            "pd_calibrated": None if calibrated is None else float(calibrated),
        },
    )
