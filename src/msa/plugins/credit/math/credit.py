"""Probability of default, exposure, recovery and expected loss (spec 7 and 8).

Calibration is a gate, not a decoration. Without a complete coefficient set the logistic
output is a ``risk_score`` and the result carries status ``uncalibrated``; the ``PD`` field
stays empty and no expected loss is produced. That rule is enforced here rather than left
to the caller, because it is the boundary the model must not be used across (spec 0).
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np

CONSTANT_HAZARD_FLAG = "constant_hazard_approximation"
PD_CLIPPED_FLAG = "pd_clipped_for_numerical_stability"
LGD_NOT_APPLICABLE = "not_applicable"
UNCALIBRATED_FLAG = "pd_uncalibrated"

#: Numerical guard only; disclosed whenever it binds (spec 7.4).
PD_EPSILON = 1e-12

DEFAULT_ICR_CAP = 2.5
DEFAULT_LEVERAGE_CAP = 3.0


def logistic(z) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.asarray(z, dtype=float)))


def logit(p, flags: list[str] | None = None) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    clipped = np.clip(p, PD_EPSILON, 1.0 - PD_EPSILON)
    if flags is not None and np.any(clipped != p):
        _add(flags, PD_CLIPPED_FLAG)
    return np.log(clipped / (1.0 - clipped))


@dataclass(frozen=True)
class PDCalibration:
    """A complete coefficient set. Any missing attribute makes the output a score (spec 7.1)."""

    segment_id: str
    default_definition: str
    horizon_months: int
    training_period: tuple[date, date]
    validation_period: tuple[date, date]
    calibrated_on: date
    discrimination: dict[str, float]
    calibration_metrics: dict[str, float]
    limitations: str
    coefficients: dict[str, float]
    #: Expected sign of each coefficient where risk direction is known in advance.
    monotone: dict[str, int] = field(default_factory=dict)
    #: Features a model may omit, with the value the calibration declares for them. Every
    #: other coefficient is a required feature (audit finding A1).
    optional_features: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if self.horizon_months < 1:
            raise ValueError("calibration horizon must be at least one month")
        if "intercept" not in self.coefficients:
            raise ValueError("a calibration must define an intercept")
        if not self.discrimination or not self.calibration_metrics:
            raise ValueError("a calibration must carry discrimination and calibration metrics")
        unknown = set(self.optional_features) - set(self.coefficients)
        if unknown:
            raise ValueError(f"optional features without a coefficient: {sorted(unknown)}")
        for name, expected in self.monotone.items():
            value = self.coefficients.get(name)
            if value is None:
                raise ValueError(f"monotone constraint on unknown coefficient {name!r}")
            if expected not in (-1, 1):
                raise ValueError("a monotone constraint must be -1 or +1")
            if value != 0.0 and np.sign(value) != expected:
                raise ValueError(
                    f"coefficient {name!r} violates its monotone constraint: "
                    f"expected sign {expected}, got {value}"
                )

    def anchored(self, external_pd: float, base_z: float) -> "PDCalibration":
        """Shift the intercept so the model reproduces an external PD at a base point.

        This calibrates the level at one point only; it says nothing about sensitivity
        elsewhere (spec 7.4).
        """
        shift = float(logit(external_pd)) - float(base_z)
        coefficients = dict(self.coefficients)
        coefficients["intercept"] = coefficients["intercept"] + shift
        return PDCalibration(**{**vars(self), "coefficients": coefficients})


class CalibrationRegistry:
    """Segment and horizon keyed lookup of approved coefficient sets."""

    def __init__(self, calibrations: list[PDCalibration] | None = None):
        self._items: dict[tuple[str, int], PDCalibration] = {}
        for item in calibrations or []:
            self.add(item)

    def add(self, calibration: PDCalibration) -> None:
        key = (calibration.segment_id, calibration.horizon_months)
        if key in self._items:
            raise ValueError(f"calibration already registered for {key}")
        self._items[key] = calibration

    def get(self, segment_id: str, horizon_months: int = 12) -> PDCalibration | None:
        return self._items.get((segment_id, horizon_months))

    def segments(self) -> list[tuple[str, int]]:
        return sorted(self._items)


@dataclass(frozen=True)
class CreditScore:
    """Logistic output plus whether it may be read as a probability of default."""

    value: np.ndarray
    calibrated: bool
    segment_id: str
    linear_predictor: np.ndarray

    @property
    def pd(self) -> np.ndarray | None:
        return self.value if self.calibrated else None

    @property
    def risk_score(self) -> np.ndarray | None:
        return None if self.calibrated else self.value


def corporate_features(
    icr,
    icr_defined,
    leverage,
    leverage_defined,
    *,
    icr_cap=DEFAULT_ICR_CAP,
    leverage_cap=DEFAULT_LEVERAGE_CAP,
) -> dict[str, np.ndarray]:
    """Bounded PD features (spec 7.2). These are model features, never displayed as ratios."""
    leverage = np.asarray(leverage, dtype=float)
    r_icr = coverage_feature(icr, icr_defined, cap=icr_cap)
    usable_lev = np.asarray(leverage_defined, dtype=bool)
    r_lev = np.where(
        usable_lev, np.log1p(np.maximum(np.where(usable_lev, leverage, 0.0), 0.0)), leverage_cap
    )
    return {
        "r_icr": r_icr,
        "r_lev": r_lev,
        "ebitda_nonpositive": (~usable_lev).astype(float),
    }


def coverage_feature(ratio, defined, *, cap=DEFAULT_ICR_CAP) -> np.ndarray:
    """``log(1 + 1/ratio)`` of a coverage ratio; ``cap`` where it is undefined or not positive."""
    ratio = np.asarray(ratio, dtype=float)
    usable = np.asarray(defined, dtype=bool) & (ratio > 0)
    return np.where(usable, np.log1p(1.0 / np.where(usable, ratio, 1.0)), cap)


def score(
    features: dict[str, np.ndarray],
    calibration: PDCalibration | None,
    *,
    segment_id: str = "unknown",
    flags: list[str] | None = None,
) -> CreditScore:
    """Logistic output for one segment (spec 7.1, 7.2).

    Without a calibration the coefficients are unknown, so an uncalibrated reference set is
    used, the output is labelled a score and ``pd_uncalibrated`` is raised.
    """
    if calibration is None:
        if flags is not None:
            _add(flags, UNCALIBRATED_FLAG)
        coefficients = _REFERENCE_COEFFICIENTS
        calibrated = False
    else:
        coefficients = calibration.coefficients
        segment_id = calibration.segment_id
        calibrated = True
    unknown = set(features) - set(coefficients) - {"intercept"}
    if calibrated and unknown:
        raise ValueError(f"calibration {segment_id!r} has no coefficient for {sorted(unknown)}")
    if calibrated:
        # A calibrated PD rests on every feature it was fitted on: none is silently zero.
        optional = calibration.optional_features
        missing = set(coefficients) - {"intercept"} - set(features) - set(optional)
        if missing:
            raise ValueError(
                f"calibration {segment_id!r} requires features {sorted(missing)} "
                "the model does not provide"
            )
        features = {**{k: v for k, v in optional.items() if k not in features}, **features}
    z = np.asarray(coefficients["intercept"], dtype=float)
    for name, value in features.items():
        z = z + coefficients.get(name, 0.0) * np.asarray(value, dtype=float)
    return CreditScore(
        value=logistic(z), calibrated=calibrated, segment_id=segment_id, linear_predictor=z
    )


#: Reference directions used only to produce an ordinal score when nothing is calibrated.
#: These are not PD coefficients and must never be presented as such.
_REFERENCE_COEFFICIENTS: dict[str, float] = {
    "intercept": -3.0,
    "r_icr": 1.0,
    "r_lev": 0.5,
    "ebitda_nonpositive": 1.0,
}


def constant_hazard(pd_12m, flags: list[str] | None = None) -> np.ndarray:
    """``h = -ln(1 - PD_12m)``; interpolation only, and always disclosed (spec 7.5)."""
    pd_12m = np.asarray(pd_12m, dtype=float)
    if np.any(pd_12m >= 1.0):
        raise ValueError("a twelve month PD of one has no finite hazard")
    if flags is not None:
        _add(flags, CONSTANT_HAZARD_FLAG)
    return -np.log1p(-pd_12m)


def survival(hazard, deltas) -> np.ndarray:
    """``S_t = exp(-sum_{k<=t} h_k * delta_k)`` (spec 7.5)."""
    hazard = np.asarray(hazard, dtype=float)
    deltas = np.broadcast_to(np.asarray(deltas, dtype=float), hazard.shape)
    if np.any(hazard < 0):
        raise ValueError("the conditional hazard must be non-negative")
    return np.exp(-np.cumsum(hazard * deltas, axis=-1))


def marginal_default(hazard, deltas) -> np.ndarray:
    """``q_t = S_{t-1} (1 - exp(-h_t delta_t))``: unconditional default in month t."""
    hazard = np.asarray(hazard, dtype=float)
    deltas = np.broadcast_to(np.asarray(deltas, dtype=float), hazard.shape)
    alive = survival(hazard, deltas)
    previous = np.concatenate([np.ones(alive.shape[:-1] + (1,)), alive[..., :-1]], axis=-1)
    return previous * (-np.expm1(-hazard * deltas))


@dataclass
class Collateral:
    """One independent collateral item (spec 8.2)."""

    kind: str
    value: float | np.ndarray
    realisation_probability: float | np.ndarray = 1.0
    haircut: float | np.ndarray = 0.0
    cost: float | np.ndarray = 0.0
    #: Expected time to recovery, in years.
    recovery_years: float | np.ndarray = 1.0
    #: Rank in the claim waterfall; lower ranks are satisfied first.
    seniority: int = 1


def recovery_pv(item: Collateral, discount_rate, value_shock=0.0) -> np.ndarray:
    """``RecPV = p_realise * V * (1 - haircut) * (1 - cost) * exp(-r * tau)`` (spec 8.2)."""
    probability = np.asarray(item.realisation_probability, dtype=float)
    haircut = np.asarray(item.haircut, dtype=float)
    cost = np.asarray(item.cost, dtype=float)
    for name, value in (
        ("realisation probability", probability),
        ("haircut", haircut),
        ("cost", cost),
    ):
        if np.any((value < 0.0) | (value > 1.0)):
            raise ValueError(f"{name} must lie in [0, 1]")
    value = np.asarray(item.value, dtype=float) * (1.0 + np.asarray(value_shock, dtype=float))
    discount = np.exp(
        -np.asarray(discount_rate, dtype=float) * np.asarray(item.recovery_years, dtype=float)
    )
    return probability * value * (1.0 - haircut) * (1.0 - cost) * discount


def loss_given_default(
    ead,
    collateral: list[Collateral] | None = None,
    *,
    discount_rate=0.0,
    value_shock=0.0,
    guarantee_pv=0.0,
    unsecured_recovery_pv=0.0,
    flags: list[str] | None = None,
):
    """``LGD = 1 - RecoveryPV / EAD`` with recovery capped at the exposure (spec 8.2).

    Returns ``(lgd, applicable)``. Where ``EAD`` is zero the money loss is zero and the LGD
    is reported as not applicable rather than as some number.
    """
    ead = np.asarray(ead, dtype=float)
    # The claim waterfall is applied before eligible recovery is summed (spec 8.2): each
    # item only reaches the exposure its seniors have left uncovered.
    remaining = np.broadcast_to(ead, ead.shape).astype(float, copy=True)
    recovery = np.zeros_like(remaining)
    claims = [
        recovery_pv(item, discount_rate, value_shock)
        for item in sorted(collateral or [], key=lambda entry: entry.seniority)
    ]
    claims.append(np.asarray(guarantee_pv, dtype=float))
    claims.append(np.asarray(unsecured_recovery_pv, dtype=float))
    for claim in claims:
        eligible = np.minimum(np.broadcast_to(claim, remaining.shape), remaining)
        recovery = recovery + eligible
        remaining = remaining - eligible
    applicable = ead > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        lgd = np.where(applicable, 1.0 - recovery / np.where(applicable, ead, 1.0), np.nan)
    if flags is not None and not bool(np.all(applicable)):
        _add(flags, f"lgd:{LGD_NOT_APPLICABLE}")
    return lgd, applicable


def expected_loss(marginal_pd, lgd, ead, discount_factors) -> np.ndarray:
    """``EL = sum_t q_t * LGD_t * EAD_t * DF_t`` within one scenario (spec 8.3)."""
    q = np.asarray(marginal_pd, dtype=float)
    lgd = np.broadcast_to(np.asarray(lgd, dtype=float), q.shape)
    ead = np.broadcast_to(np.asarray(ead, dtype=float), q.shape)
    df = np.broadcast_to(np.asarray(discount_factors, dtype=float), q.shape)
    if np.any(ead < 0.0):
        raise ValueError("EAD must be non-negative")
    # ``loss_given_default`` deliberately reports LGD as undefined when EAD is zero.
    # The corresponding money loss is nevertheless exactly zero (spec 8.2), so do
    # not let the otherwise useful NaN marker contaminate the trajectory sum.
    applicable_lgd = np.where(ead > 0.0, lgd, 0.0)
    return np.sum(q * applicable_lgd * ead * df, axis=-1)


def delta_expected_loss(stress_el, base_el) -> np.ndarray:
    return np.asarray(stress_el, dtype=float) - np.asarray(base_el, dtype=float)


def _add(flags: list[str], flag: str) -> None:
    if flag not in flags:
        flags.append(flag)
