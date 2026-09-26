"""The risk of one credit position: scenario draws -> driver shocks -> the family -> risk.

Nothing here depends on the instrument type. The position's ``CreditFamily`` turns driver
shocks into monthly trajectories, metrics and PD features; this module turns those into the
credit, market, liquidity and covenant results, their P5/P50/P95 over the run's joint
realisations, Shapley contributions by channel and the reverse stress test.

The model reads the run's joint scenario matrix and uses the parameters that move a credit
factor; parameters of other families' factors (an equity index, a currency pair) belong to
the same realisations but do not shock a borrower.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from msa.contracts.common import VersionStamp
from msa.contracts.graph import TransmissionGraph
from msa.contracts.risk import ApplicabilityLimits, Interval, Quantiles
from msa.plugin_sdk.calc import (
    DEFAULT_TOLERANCES,
    NO_PATH_FLAG,
    ScenarioSet,
    code_sha256,
    edge_elasticities,
    estimate,
    expected_shortfall,
    factor_change,
    factor_signal,
    shapley_contributions,
    worst,
)

from .contracts import (
    AxisSummary,
    CovenantResult,
    CreditProfile,
    CreditResult,
    LiquidityResult,
    MonthlySeries,
    ReverseStressDirection,
    ReverseStressResult,
    RiskResult,
    ShapleyContribution,
    Trajectory,
)
from .factors import BY_ID as FACTORS
from .families import FAMILIES, family_for
from .family import DRIVERS, CreditFamily, Inputs, driver_of
from .math import covenants, impact, reverse_stress
from .math.bonds import BondTerms
from .math.calendar import Calendar
from .math.credit import (
    CalibrationRegistry,
    CreditScore,
    constant_hazard,
    expected_loss,
    marginal_default,
    score,
)

MODEL_VERSION = "3.3.0"
SYNTHETIC_CALIBRATION_FLAG = "calibration_synthetic"
LGD_NOT_APPLICABLE_FLAG = "lgd_not_applicable"
COVENANT_OUTSIDE_PREFIX = "covenant_outside_horizon:"
COVENANT_UNDEFINED_PREFIX = "covenant_metric_undefined:"
REVERSE_UNDEFINED_PREFIX = "reverse_stress_undefined:"
REVERSE_DIRECTION_UNDEFINED_FLAG = "reverse_stress_direction_undefined"

#: Gaps of any model that send a result to review (spec 19); models add their own.
GENERIC_REVIEW_FLAGS = frozenset({"numerical_tolerance_not_met", SYNTHETIC_CALIBRATION_FLAG})
REVIEW_PREFIXES = (
    COVENANT_OUTSIDE_PREFIX,
    "covenant_metric_unavailable:",
    COVENANT_UNDEFINED_PREFIX,
    "profile:",
)
INVALID_FLAGS = frozenset({"negative_cost", "cash_iteration_not_converged"})


def review_flags() -> frozenset[str]:
    return GENERIC_REVIEW_FLAGS.union(*(family.review_flags for family in FAMILIES))


def review_triggers(flags) -> list[str]:
    """The flags of a result that make it ``needs_review``."""
    known = review_flags()
    return [f for f in flags if f in known or f.startswith(REVIEW_PREFIXES)]


@dataclass(frozen=True)
class AssetRiskInput:
    """One credit position and its approved transmission graph on a declared valuation date."""

    profile: CreditProfile
    graph: TransmissionGraph
    as_of: date
    horizon: int = 12

    def __post_init__(self):
        if not 1 <= self.horizon <= 360:
            raise ValueError("horizon must be between 1 and 360 months")


@dataclass(frozen=True)
class BondMarketCalibration:
    """Approved risk-neutral market inputs for one bond position."""

    terms: BondTerms
    hazard: np.ndarray | float
    risk_free: np.ndarray | float
    basis: np.ndarray | float = 0.0
    spread_change: np.ndarray | float = 0.0


@dataclass
class ModelRegistry:
    """Approved calibrations and process rules injected into the pure calculation."""

    calibrations: CalibrationRegistry = field(default_factory=CalibrationRegistry)
    axis_rules: list[impact.ThresholdRule] = field(default_factory=list)
    segment_by_okved: dict[str, str] = field(default_factory=dict)
    #: Segment by asset type, when it differs from the asset model's own segment.
    segment_by_asset_type: dict[str, str] = field(default_factory=dict)
    bond_market: dict[str, BondMarketCalibration] = field(default_factory=dict)
    #: Read bond terms from the position when no market calibration is loaded (flagged).
    market_from_profile: bool = False
    #: The PD coefficients are synthetic (demo stand): every PD result is flagged for review.
    synthetic_calibration: bool = False
    registry_id: str = "none"
    model_versions: dict[str, str] = field(
        default_factory=lambda: {
            name: MODEL_VERSION
            for name in (
                "position_risk",
                "transmission",
                "operating",
                "credit",
                "market",
                "portfolio",
                "shapley",
                "reverse_stress",
            )
        }
    )

    def segment(self, profile: CreditProfile, default: str) -> str:
        return (
            self.segment_by_okved.get(profile.okved)
            or self.segment_by_asset_type.get(profile.asset_type)
            or default
        )


@dataclass
class _Evaluation:
    series: dict[str, np.ndarray]
    metrics: dict[str, np.ndarray]
    credit_score: CreditScore
    flags: list[str]


@dataclass
class _Asset:
    """What one asset's calculation holds fixed: its model, inputs, calendar and segment."""

    input: AssetRiskInput
    model: CreditFamily
    inputs: Inputs
    calendar: Calendar
    registry: ModelRegistry
    segment: str

    def evaluate(self, drivers) -> _Evaluation:
        evaluation = self.model.evaluate(self.inputs, self.calendar, drivers)
        flags = list(evaluation.flags)
        credit = score(
            evaluation.features,
            self.registry.calibrations.get(self.segment, 12),
            segment_id=self.segment,
            flags=flags,
        )
        series = {**evaluation.series, "risk_score": credit.value}
        return _Evaluation(series, evaluation.metrics, credit, flags)

    def expected_loss(self, evaluation: _Evaluation):
        pd_path = np.asarray(evaluation.credit_score.pd, dtype=float)
        marginal = marginal_default(constant_hazard(pd_path), self.calendar.deltas())
        profile = self.input.profile
        return expected_loss(
            marginal,
            np.full(pd_path.shape, float(profile.lgd)),
            np.full(pd_path.shape, profile.exposure),
            self.calendar.discount_factors(0.0),
        )


def run_asset(
    input: AssetRiskInput,
    scenario_set: ScenarioSet,
    model_registry: ModelRegistry | None,
    seed: int,
) -> RiskResult:
    """The risk of one credit position: ``RiskResult`` of spec 20."""
    registry = model_registry or ModelRegistry()
    profile = input.profile
    model = family_for(profile.asset_type)
    flags: list[str] = []
    asset = _Asset(
        input=input,
        model=model,
        inputs=model.inputs(profile, flags),
        calendar=Calendar(input.as_of, input.horizon),
        registry=registry,
        segment=registry.segment(profile, model.segment),
    )
    sampled = scenario_set.sample(seed)
    central = {
        name: marginal.central_value() for name, marginal in scenario_set.marginals().items()
    }
    random_values = {name: sampled.stacked(name) for name in sampled.names}  # (replicate, point)
    # The realisations also draw the uncertain elasticities of the graph's edges; the
    # central evaluation, Shapley and reverse stress stay on the central graph.
    elasticities = edge_elasticities(
        input.graph, seed, scenario_set.points, scenario_set.replicates
    )

    base = asset.evaluate(_zero_drivers((), input.horizon))
    stress = asset.evaluate(_driver_shocks(input, scenario_set, central, flags=flags))
    random = asset.evaluate(
        _driver_shocks(input, scenario_set, random_values, flags=flags, elasticities=elasticities)
    )
    for item in (*base.flags, *stress.flags, *random.flags):
        _add(flags, item)

    calibrated = stress.credit_score.calibrated
    money = calibrated and model.lgd_applicable
    if calibrated and not model.lgd_applicable:
        _add(flags, LGD_NOT_APPLICABLE_FLAG)
    base_el = asset.expected_loss(base) if money else None
    stress_el = asset.expected_loss(stress) if money else None

    if money:
        target_name, target_unit = "delta_expected_loss", "RUB_million"
        target_draws = np.asarray(asset.expected_loss(random), dtype=float) - float(
            np.asarray(base_el)
        )
        central_target = float(np.asarray(stress_el) - np.asarray(base_el))
    else:
        target_name = "pd" if calibrated else "risk_score"
        target_unit = "fraction"
        target_draws = np.asarray(random.credit_score.value[..., -1], dtype=float)
        central_target = float(np.asarray(stress.credit_score.value[..., -1]))
    target_draws = np.broadcast_to(target_draws, (scenario_set.replicates, scenario_set.points))

    quantile = _quantiles(target_name, target_unit, target_draws)
    interval = _interval(target_name, target_unit, target_draws)
    if not interval.within_tolerance:
        _add(flags, "numerical_tolerance_not_met")

    credit = CreditResult(
        calibrated=calibrated,
        segment_id=stress.credit_score.segment_id,
        risk_score=None if calibrated else central_target,
        pd=float(stress.credit_score.pd[..., -1]) if calibrated else None,
        lgd=float(profile.lgd) if model.lgd_applicable else None,
        lgd_applicable=model.lgd_applicable,
        ead=profile.exposure,
        expected_loss=None if stress_el is None else float(np.asarray(stress_el)),
        delta_expected_loss=None if stress_el is None else central_target,
    )

    covenant_results, reverse_results = _covenants(asset, scenario_set, stress, random, flags)
    shapley = _shapley(asset, scenario_set, central, money, seed, flags)
    liquidity = _liquidity(stress)
    market, position_draws = None, None
    if model.has_market:
        realised = (
            (
                base.credit_score.pd[..., -1],
                stress.credit_score.pd[..., -1],
                random.credit_score.pd[..., -1],
            )
            if calibrated
            else None
        )
        market, position_draws = model.market(profile, asset.inputs, registry, flags, realised)
    if calibrated and registry.synthetic_calibration:
        _add(flags, SYNTHETIC_CALIBRATION_FLAG)

    axes = _axes(asset, credit, market, liquidity, covenant_results, interval)
    status = "ok" if calibrated else "uncalibrated"
    if review_triggers(flags):
        status = worst(status, "needs_review")
    if any(item.startswith("out_of_domain:") or item in INVALID_FLAGS for item in flags):
        status = "invalid"
    if profile.status == "needs_review":
        status = worst(status, "needs_review")
        for item in profile.flags:
            _add(flags, f"profile:{item}")
    if status in {"needs_review", "incomplete", "invalid"} and not flags:
        flags.append(status)

    stamp = VersionStamp(
        model_version=MODEL_VERSION,
        prompt_version="not_applicable",
        code_sha256=code_sha256(),
        macro_draws_sha256=sampled.sha256,
    )
    return RiskResult(
        asset_id=profile.asset_id,
        as_of=input.as_of,
        horizon=input.horizon,
        status=status,
        model_id=model.model_id,
        seed=seed,
        versions=stamp,
        model_versions=registry.model_versions,
        macro_draws_sha256=sampled.sha256,
        input_sources=_input_sources(profile),
        base=_trajectory("base", asset, base.series),
        stress=_trajectory("stress", asset, stress.series),
        credit=credit,
        market=market,
        liquidity=liquidity,
        covenants=covenant_results,
        quantiles={
            target_name: quantile,
            **_decision_quantiles(asset, base, random, calibrated, position_draws, flags),
        },
        intervals={target_name: interval},
        shapley=shapley,
        reverse_stress=reverse_results,
        axes=axes,
        flags=flags,
        coverage={"input_data": float(profile.dq), "trajectory": 1.0},
        aggregation_draws=(
            np.asarray(target_draws, dtype=float).reshape(-1).tolist() if money else None
        ),
        limits=ApplicabilityLimits(
            approved_uses=["scenario_analysis", "early_warning", "manual_review_ranking"],
            prohibited_uses=[
                "automatic_credit_decision",
                "regulatory_pd_lgd_ead",
                "ifrs9_ecl",
                "accounting_or_regulatory_reporting",
                "market_fair_value",
            ],
            note="Shadow calculation until empirical calibration and independent validation.",
        ),
    )


def _zero_drivers(lead: tuple[int, ...], horizon: int) -> dict[str, np.ndarray]:
    return {name: np.zeros((*lead, horizon)) for name in DRIVERS}


def credit_parameters(scenario_set) -> dict:
    """Parameters that shock a borrower: credit factors, and inputs without a factor."""
    return {
        name: parameter
        for name, parameter in scenario_set.parameters.items()
        if parameter.factor is None or driver_of(parameter.factor) is not None
    }


def driver_signal(
    graph, parameter, okved, value, horizon, *, flags, elasticities=None
) -> np.ndarray | None:
    """The monthly signal one credit parameter sends to its driver for an asset of ``okved``."""
    return factor_signal(
        graph,
        parameter,
        FACTORS[parameter.factor],
        okved,
        value,
        horizon,
        flags=flags,
        elasticities=elasticities,
    )


def driver_change(driver: str, signal) -> np.ndarray:
    """A driver signal as the change a family reads: relative, or days and rate points."""
    return factor_change(FACTORS["credit." + driver], signal)


def _driver_shocks(input, scenario_set, values, *, flags, elasticities=None) -> dict:
    """Monthly shock of every driver of this asset under the given parameter values."""
    horizon = input.horizon
    signals: dict[str, list[np.ndarray]] = {name: [] for name in DRIVERS}
    for name, parameter in credit_parameters(scenario_set).items():
        if parameter.factor is None or parameter.channel is None:
            _add(flags, f"scenario_parameter_unmapped:{name}")
            continue
        signal = driver_signal(
            input.graph,
            parameter,
            input.profile.okved,
            values[name],
            horizon,
            flags=flags,
            elasticities=elasticities,
        )
        if signal is None:
            _add(flags, f"{NO_PATH_FLAG}:{name}")
            continue
        signals[driver_of(parameter.factor)].append(signal)

    lead = _lead_shape(values[name] for name in credit_parameters(scenario_set))
    result = _zero_drivers(lead, horizon)
    for driver, parts in signals.items():
        if parts:
            result[driver] = driver_change(driver, np.sum(np.stack(parts), axis=0))
    return result


def _lead_shape(values: Iterable) -> tuple[int, ...]:
    shapes = [np.asarray(value).shape for value in values]
    return np.broadcast_shapes(*shapes) if shapes else ()


def _liquidity(stress: _Evaluation) -> LiquidityResult | None:
    """The liquidity axis, for models that track cash; others have none to report."""
    paths = stress.metrics
    if "cash_headroom" not in paths or "funding_gap" not in paths:
        return None
    return LiquidityResult(
        min_cash_headroom=float(np.nanmin(paths["cash_headroom"])),
        max_funding_gap=float(np.nanmax(paths["funding_gap"])),
        limit_excess=float(np.nanmax(paths.get("limit_excess", np.array([0.0])))),
    )


def _covenants(asset: _Asset, scenario_set, stress, random, flags):
    tested, outside = covenants.definitions(asset.input.profile, asset.calendar)
    for covenant_id in outside:
        _add(flags, f"{COVENANT_OUTSIDE_PREFIX}{covenant_id}")
    outcomes, reverse = [], []
    for definition in tested:
        path = stress.metrics.get(definition.metric)
        random_path = random.metrics.get(definition.metric)
        if path is None or random_path is None:
            _add(flags, f"covenant_metric_unavailable:{definition.covenant_id}")
            continue
        worst_headroom = covenants.worst_headroom(definition, path, asset.calendar.month_ends())
        headroom = float(np.asarray(worst_headroom["headroom"]))
        if not np.isfinite(headroom):
            # The ratio has no meaning on the stress path (e.g. leverage at EBITDA <= 0):
            # there is no headroom to report, and no boundary for reverse stress to find.
            _add(flags, f"{COVENANT_UNDEFINED_PREFIX}{definition.covenant_id}")
            continue
        probability = covenants.breach_probability(definition, random_path)
        outcomes.append(
            CovenantResult(
                covenant_id=definition.covenant_id,
                metric=definition.metric,
                operator=definition.operator,
                threshold=float(np.asarray(definition.threshold)),
                min_headroom=headroom,
                breach_month=worst_headroom["month"] if probability > 0 else None,
                breach_date=worst_headroom["date"] if probability > 0 else None,
                breach_probability=probability,
                cure_period_months=definition.cure_period_months,
            )
        )

        direction = reverse_stress.Direction(
            components={
                name: marginal.central_value()
                for name, marginal in scenario_set.marginals().items()
                if name in credit_parameters(scenario_set)
            },
            lambda_max=_lambda_max(scenario_set),
            plausibility="Confirmed management scenario scaled proportionally.",
        )
        if not direction.norm() > 0:
            # A scenario centred on zero (a symmetric range, a zero shock) has no direction
            # to scale along; the covenant itself is tested as usual.
            _add(flags, REVERSE_DIRECTION_UNDEFINED_FLAG)
            continue

        def metric_at(
            lam,
            metric_name=definition.metric,
            check_month=definition.check_months[0],
        ):
            values = {
                name: marginal.central_value() * lam
                for name, marginal in scenario_set.marginals().items()
                if name in credit_parameters(scenario_set)
            }
            drivers = _driver_shocks(asset.input, scenario_set, values, flags=[])
            metric_path = asset.evaluate(drivers).metrics[metric_name]
            return float(np.asarray(metric_path)[..., check_month - 1])

        item = reverse_stress.search(
            metric_at, definition.threshold, definition.operator, direction
        )
        if not (np.isfinite(item.metric_before) and np.isfinite(item.metric_after)):
            # The scaled scenario crosses into a region where the ratio is undefined.
            _add(flags, f"{REVERSE_UNDEFINED_PREFIX}{definition.covenant_id}")
            continue
        reverse.append(_reverse_contract(definition.covenant_id, item))
    return outcomes, reverse


def _lambda_max(scenario_set):
    """Largest scale that keeps every relative shock above -100 % (spec 3.2: xi > -1)."""
    bounds = [
        0.999 / -central
        for name, marginal in scenario_set.marginals().items()
        if name in credit_parameters(scenario_set)
        and scenario_set.parameters[name].unit == "fraction"
        and (central := marginal.central_value()) < 0
    ]
    return min([reverse_stress.DEFAULT_LAMBDA_MAX, *bounds])


def _reverse_contract(target, item):
    return ReverseStressResult(
        target=target,
        status=item.status,
        lambda_star=item.lambda_star,
        interval=item.interval,
        direction=ReverseStressDirection(
            components=item.direction.components,
            norm=item.direction.norm(),
            lambda_max=item.direction.lambda_max,
            plausibility=item.direction.plausibility,
        ),
        shock=item.shock or None,
        metric_before=item.metric_before,
        metric_after=item.metric_after,
        continuous=item.continuous,
        later_crossings=item.later_crossings,
        flags=list(item.flags),
    )


def _shapley(asset: _Asset, scenario_set, central, money, seed, flags):
    channels = sorted({p.channel for p in credit_parameters(scenario_set).values() if p.channel})
    if not channels:
        return []

    def value(active):
        values = {
            name: central[name] if parameter.channel in active else 0.0
            for name, parameter in credit_parameters(scenario_set).items()
        }
        evaluation = asset.evaluate(_driver_shocks(asset.input, scenario_set, values, flags=[]))
        if money:
            return float(np.asarray(asset.expected_loss(evaluation)))
        return float(np.asarray(evaluation.credit_score.value[..., -1]))

    answer = shapley_contributions(channels, value, seed)
    for item in answer.flags:
        _add(flags, item)
    return [
        ShapleyContribution(
            channel=name,
            contribution=value,
            halfwidth=answer.halfwidths.get(name, 0.0),
        )
        for name, value in answer.contributions.items()
    ]


def _quantiles(name, unit, draws, *, tail=True):
    values = np.asarray(draws, dtype=float).reshape(-1)
    p05, p50, p95 = np.percentile(values, [5, 50, 95], method="linear")
    return Quantiles(
        name=name,
        unit=unit,
        p05=float(p05),
        p50=float(p50),
        p95=float(p95),
        # The loss tail only: a shortfall of ICR or of a price change is not a risk measure.
        # ES95 >= P95 holds exactly; on equal draws the float sum may undercut it by an ulp.
        es95=max(expected_shortfall(values), float(p95)) if tail else None,
    )


def _interval(name, unit, draws):
    values = np.asarray(draws, dtype=float)
    per_replicate = np.percentile(values, 95, axis=1, method="linear")
    value = estimate(per_replicate)
    tolerance = DEFAULT_TOLERANCES["p95"]
    return Interval(
        name=f"p95_{name}",
        unit=unit,
        mean=value.mean,
        standard_error=value.standard_error,
        halfwidth=value.halfwidth,
        replicates=value.replicates,
        within_tolerance=tolerance.satisfied_by(value),
    )


def _trajectory(label, asset: _Asset, series):
    specs = {item.name: item for item in asset.model.series}
    items = {}
    for name, values in series.items():
        array = np.asarray(values, dtype=float)
        if array.ndim != 1:
            raise ValueError(f"central trajectory {name!r} must be one-dimensional")
        spec = specs.get(name)
        unit, kind = (spec.unit, spec.kind) if spec else ("fraction", "probability")
        items[name] = MonthlySeries(
            name=name,
            unit=unit,
            kind=kind,
            values=[None if not np.isfinite(value) else float(value) for value in array],
        )
    return Trajectory(
        label=label,
        horizon=asset.calendar.horizon,
        month_ends=asset.calendar.month_ends(),
        series=items,
    )


def _decision_quantiles(asset: _Asset, base, random, calibrated, position_draws, flags):
    """P5/P50/P95 of the model's decision metrics at the horizon end, same realisations.

    The advisory rules act on these medians (TZ 3.6), together with the change of PD (or of
    the score, when uncalibrated) and the bond position value.
    """
    result = {}
    for name in asset.model.decision_metrics:
        path = random.metrics.get(name)
        if path is None:
            continue
        values = np.asarray(path, dtype=float)[..., -1].reshape(-1)
        finite = values[np.isfinite(values)]
        if finite.size < values.size:
            _add(flags, f"{name}_undefined_in_some_scenarios")
        if finite.size * 2 < values.size:
            continue
        result[name] = _quantiles(name, asset.model.unit(name), finite, tail=False)
    score_name = "delta_pd" if calibrated else "delta_risk_score"
    realised = np.asarray(random.credit_score.value, dtype=float)[..., -1]
    change = realised - float(np.asarray(base.credit_score.value)[..., -1])
    result[score_name] = _quantiles(score_name, "fraction", change, tail=False)
    if position_draws is not None:
        result["position_price_change"] = _quantiles(
            "position_price_change", "RUB_million", position_draws, tail=False
        )
    return result


def _axes(asset: _Asset, credit, market, liquidity, covenant_results, interval):
    min_headroom = min((item.min_headroom for item in covenant_results), default=None)
    breach = max((item.breach_probability for item in covenant_results), default=None)
    results = [
        impact.credit_axis(
            pd=credit.pd,
            risk_score=credit.risk_score,
            lgd=credit.lgd,
            ead=credit.ead,
            expected_loss=credit.expected_loss,
            delta_expected_loss=credit.delta_expected_loss,
        ),
        impact.market_axis(
            price=None if market is None else market.stress_price,
            price_change=None if market is None else market.price_change,
            duration=None if market is None else market.duration,
            convexity=None if market is None else market.convexity,
        ),
        impact.liquidity_axis(
            cash_headroom=None if liquidity is None else liquidity.min_cash_headroom,
            funding_gap=None if liquidity is None else liquidity.max_funding_gap,
            limit_excess=None if liquidity is None else liquidity.limit_excess,
        ),
        impact.covenant_axis(headroom=min_headroom, breach_probability=breach),
        impact.data_and_model_axis(
            data_quality=float(asset.input.profile.dq),
            numerical_halfwidth=interval.halfwidth,
            calibrated=credit.calibrated,
        ),
    ]
    if asset.model.has_market and (market is None or market.stress_price is None):
        results[1].reason = "Рыночная калибровка облигации не загружена."
        results[1].recommendation = "Загрузите утверждённые кривые интенсивности и дисконтирования."
        results[1].flags.append("market_calibration_missing")
    rules = asset.registry.axis_rules
    return [AxisSummary(**vars(item)) for item in impact.apply_rules(results, rules)]


def _input_sources(profile):
    result = {
        name: sorted({e.source_id for e in parameter.evidence})
        for name, parameter in profile.financials.items()
    }
    for name, evidence in profile.field_evidence.items():
        result[name] = sorted({item.source_id for item in evidence})
    return result


def _add(flags, flag):
    if flag not in flags:
        flags.append(flag)
