"""Portfolio slices from the positions' contributions (spec 16).

Each slice adds up one measure: the credit expected-loss change, the market P&L. Losses of
the admitted positions are summed inside each joint realisation, and only then turned into
quantiles; slices are never added to each other. Coverage is measured on the slice's own
basis — EAD for credit, position value for market — over every position of the run that
belongs to the slice, calculated or not; a position whose exposure cannot be measured makes
the slice incomplete rather than disappearing from it.

Within a slice only compatible contributions are combined: the slice unit (money in the
base currency), the run horizon and the run's scenario set.
"""

from msa.contracts.result import (
    CalculationResult,
    Coverage,
    ExcludedPosition,
    PortfolioResult,
    PositionContribution,
    Quantiles,
    SliceResult,
)
from msa.platform.registry import Registry

from .dispatch import resolved_unit
from .portfolio import AssetLoss, aggregate

INCOMPATIBLE_PREFIX = "incompatible:"
UNKNOWN_EXPOSURE_FLAG = "exposure_unknown"
STATUS_ORDER = ("ok", "needs_review", "incomplete", "invalid")


def aggregate_slices(
    run_id: str,
    results: list[CalculationResult],
    *,
    draws: dict[tuple[str, str], list[float]],
    exposures: dict[str, dict[str, float | None]],
    registry: Registry,
    base_currency: str,
    as_of,
    horizon: int,
    seed: int,
    scenario_id: str,
    macro_draws_sha256: str,
) -> PortfolioResult:
    """``draws`` maps (position, slice) to its loss realisations in the shared order;
    ``exposures`` maps a position to its exposure on each slice it belongs to."""
    ids = [result.position_id for result in results]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate position result")
    by_position = {result.position_id: result for result in results}
    members: dict[str, list[str]] = {}
    for position_id in sorted(by_position):
        result = by_position[position_id]
        slices = set(exposures.get(position_id, {})) | {c.slice_id for c in result.contributions}
        for slice_id in slices:
            members.setdefault(slice_id, []).append(position_id)

    slices = {}
    for slice_id in sorted(members):
        if slice_id not in registry.slices:
            continue
        slices[slice_id] = _slice(
            slice_id,
            [by_position[p] for p in members[slice_id]],
            draws=draws,
            exposures=exposures,
            registry=registry,
            base_currency=base_currency,
            horizon=horizon,
            scenario_id=scenario_id,
        )
    in_slices = {p for ids in members.values() for p in ids}
    not_aggregated = [
        ExcludedPosition(
            position_id=result.position_id,
            status=result.status,
            reason="; ".join(result.flags) or "the model contributes to no portfolio slice",
        )
        for result in sorted(results, key=lambda r: r.position_id)
        if result.position_id not in in_slices
    ]
    status = "ok"
    flags: list[str] = []
    for item in slices.values():
        status = max(status, item.status, key=STATUS_ORDER.index)
    if not_aggregated:
        flags.append("positions_outside_slices")
        status = max(status, "needs_review", key=STATUS_ORDER.index)
    model_versions = {
        f"{result.position_id}:{result.model_id}": result.model_version
        for result in sorted(results, key=lambda r: r.position_id)
    }
    return PortfolioResult(
        run_id=run_id,
        as_of=as_of,
        horizon=horizon,
        seed=seed,
        base_currency=base_currency,
        scenario_id=scenario_id,
        macro_draws_sha256=macro_draws_sha256,
        slices=slices,
        not_aggregated=not_aggregated,
        model_versions=model_versions,
        status=status,
        flags=flags,
    )


def _slice(slice_id, results, *, draws, exposures, registry, base_currency, horizon, scenario_id):
    spec = registry.slices[slice_id]
    unit = resolved_unit(spec.unit, base_currency)
    losses, approved, rules, unknown, flags = [], set(), {}, [], []
    measures = set()
    for result in results:
        contribution = next((c for c in result.contributions if c.slice_id == slice_id), None)
        exposure = exposures.get(result.position_id, {}).get(slice_id)
        if contribution is not None and contribution.exposure is not None:
            exposure = contribution.exposure
        if exposure is None:
            unknown.append(result.position_id)
        values, status, reason = None, result.status, "; ".join(result.flags) or None
        if contribution is not None:
            measures.add(contribution.measure)
            problem = _incompatible(contribution, unit, horizon, scenario_id)
            if problem:
                reason = INCOMPATIBLE_PREFIX + problem
                status = "invalid"
            elif contribution.enters:
                # A result that needs review enters only under an approved rule (spec 19).
                values = draws.get((result.position_id, slice_id))
                if contribution.admission.startswith("admitted:"):
                    approved.add(result.position_id)
                    rules[result.position_id] = contribution.admission.partition(":")[2]
            else:
                reason = contribution.admission.partition(":")[2] or reason
        losses.append(
            AssetLoss(
                asset_id=result.position_id,
                draws=values,
                ead=float(exposure or 0.0),
                status=status,
                exclusion_reason=reason,
            )
        )
    aggregated = aggregate(
        losses, coverage_limit=spec.coverage_limit, approved_needs_review=frozenset(approved)
    )
    status, flags = aggregated.status, list(aggregated.flags)
    if unknown:
        status = "incomplete"
        flags.append(UNKNOWN_EXPOSURE_FLAG)
    included_by_rule = sorted(set(aggregated.included) & approved)
    if included_by_rule:
        # The rule and the positions it admitted are part of the disclosed result.
        flags += [f"inclusion_rule:{rule}" for rule in sorted({rules[p] for p in included_by_rule})]
        flags += [f"included_by_rule:{position_id}" for position_id in included_by_rule]
    has_loss = bool(aggregated.included)
    measure = measures.pop() if len(measures) == 1 else slice_id
    return SliceResult(
        slice_id=slice_id,
        measure=measure,
        unit=unit,
        status=status,
        loss_quantiles=Quantiles(
            name=slice_id,
            unit=unit,
            p05=aggregated.p05,
            p50=aggregated.p50,
            p95=aggregated.p95,
            es95=aggregated.expected_shortfall_95,
        )
        if has_loss
        else None,
        mean_loss=aggregated.mean_loss if has_loss else None,
        value_at_risk_95=aggregated.value_at_risk_95 if has_loss else None,
        expected_shortfall_95=aggregated.expected_shortfall_95 if has_loss else None,
        coverage=Coverage(
            basis=spec.exposure_basis,
            covered_share=aggregated.covered_ead_share,
            limit=spec.coverage_limit,
            unknown_exposure=sorted(unknown),
        ),
        herfindahl=aggregated.herfindahl,
        included=aggregated.included,
        excluded=[
            ExcludedPosition(position_id=e["asset_id"], status=e["status"], reason=e["reason"])
            for e in aggregated.excluded
        ],
        contributions=[
            PositionContribution(
                position_id=c["asset_id"],
                mean_loss=c["mean_loss"],
                expected_shortfall_contribution=c["expected_shortfall_contribution"],
                p95_standalone=c["p95_standalone"],
            )
            for c in aggregated.contributions
        ],
        sum_of_individual_p95=aggregated.sum_of_individual_p95 if has_loss else None,
        flags=flags,
    )


def _incompatible(contribution, unit, horizon, scenario_id) -> str | None:
    if contribution.unit != unit:
        return f"unit {contribution.unit}, slice {unit}"
    if contribution.horizon != horizon:
        return f"horizon {contribution.horizon}, run {horizon}"
    if contribution.scenario_id != scenario_id:
        return "another scenario set"
    return None
