"""Portfolio aggregation arithmetic (spec 16), used by every slice (``aggregation``).

Losses are summed inside each joint realisation and only then turned into quantiles. The
sum of individual P95 values is descriptive statistics and is never reported as the
portfolio P95.

An asset that could not be computed does not quietly disappear: the covered share of EAD,
the excluded assets and the reason for each exclusion are part of the result.
"""

from dataclasses import dataclass, field

import numpy as np

INCOMPLETE_FLAG = "portfolio_incomplete"
#: Uncovered EAD above this share turns the portfolio result into ``incomplete``.
DEFAULT_COVERAGE_LIMIT = 0.05


@dataclass
class AssetLoss:
    """One asset's loss draws in the common realisation order."""

    asset_id: str
    draws: np.ndarray | None
    ead: float
    status: str = "ok"
    exclusion_reason: str | None = None


@dataclass
class Aggregate:
    loss_draws: np.ndarray
    p05: float
    p50: float
    p95: float
    expected_shortfall_95: float
    value_at_risk_95: float
    mean_loss: float
    herfindahl: float
    covered_ead_share: float
    included: list[str]
    excluded: list[dict[str, str]]
    sum_of_individual_p95: float
    contributions: list[dict[str, float]] = field(default_factory=list)
    status: str = "ok"
    flags: list[str] = field(default_factory=list)


def sum_by_realisation(losses: list[AssetLoss]) -> np.ndarray:
    """``Loss_j = sum_i Loss_ij``; every asset must share the realisation order."""
    arrays = [np.asarray(item.draws, dtype=float) for item in losses if item.draws is not None]
    if not arrays:
        return np.zeros(0)
    length = arrays[0].shape[0]
    if any(array.shape[0] != length for array in arrays):
        raise ValueError("every asset must supply the same number of joint realisations")
    return np.sum(arrays, axis=0)


def value_at_risk(draws, level: float = 0.95) -> float:
    return float(np.percentile(np.asarray(draws, dtype=float), level * 100.0, method="linear"))


def expected_shortfall(draws, level: float = 0.95) -> float:
    """``ES = 1/(1-a) * integral_a^1 VaR_u du`` (spec 16).

    On a discrete sample the integral becomes a weighted sum that gives the boundary
    observation exactly the mass the tail still needs, rather than dropping or double
    counting it.
    """
    values = np.sort(np.asarray(draws, dtype=float))
    n = values.size
    if n == 0:
        return 0.0
    tail = 1.0 - level
    if tail <= 0:
        return float(values[-1])
    # Each order statistic carries mass 1/n; take the part of it above the level.
    upper = np.arange(1, n + 1) / n
    lower = np.arange(0, n) / n
    weight = np.clip(upper - np.maximum(lower, level), 0.0, None)
    return float(np.sum(values * weight) / tail)


def herfindahl(exposures: dict[str, float]) -> float:
    """``HHI = sum_i share_i^2`` on exposure at default (spec 16)."""
    total = sum(exposures.values())
    if total <= 0:
        return 0.0
    return float(sum((value / total) ** 2 for value in exposures.values()))


def aggregate(
    losses: list[AssetLoss],
    *,
    coverage_limit: float = DEFAULT_COVERAGE_LIMIT,
    approved_needs_review: frozenset[str] = frozenset(),
) -> Aggregate:
    """Aggregate approved asset losses with explicit exclusion disclosure.

    ``invalid`` and ``uncalibrated`` values are never losses suitable for aggregation.
    ``needs_review`` is included only when an upstream policy explicitly names the asset.
    """
    flags: list[str] = []
    included = [
        item
        for item in losses
        if item.draws is not None
        and (
            item.status == "ok"
            or (item.status == "needs_review" and item.asset_id in approved_needs_review)
        )
    ]
    included_ids = {item.asset_id for item in included}
    excluded = [
        {
            "asset_id": item.asset_id,
            "status": item.status,
            "reason": item.exclusion_reason or _exclusion_reason(item),
        }
        for item in losses
        if item.asset_id not in included_ids
    ]
    total_ead = sum(item.ead for item in losses)
    covered = sum(item.ead for item in included)
    coverage = 1.0 if total_ead <= 0 else covered / total_ead

    draws = sum_by_realisation(included)
    status = "ok"
    if any(item.status == "needs_review" for item in included):
        # Admitted by an approved rule; the portfolio discloses it rather than hiding it.
        status = "needs_review"
        flags.append("needs_review_included_by_rule")
    if excluded:
        # The portfolio is incomplete once the uncovered share passes the approved limit.
        if 1.0 - coverage > coverage_limit:
            status = "incomplete"
            flags.append(INCOMPLETE_FLAG)
        else:
            status = "needs_review"
            flags.append("portfolio_exclusions")
    if draws.size == 0:
        return Aggregate(
            loss_draws=draws,
            p05=0.0,
            p50=0.0,
            p95=0.0,
            expected_shortfall_95=0.0,
            value_at_risk_95=0.0,
            mean_loss=0.0,
            herfindahl=0.0,
            covered_ead_share=coverage,
            included=[],
            excluded=excluded,
            sum_of_individual_p95=0.0,
            status="incomplete" if losses else "ok",
            flags=flags,
        )

    p05, p50, p95 = (float(value) for value in np.percentile(draws, [5, 50, 95], method="linear"))
    var95 = value_at_risk(draws)
    # ES95 >= VaR95 holds exactly; on equal draws the float sum may undercut it by an ulp.
    portfolio_es = max(expected_shortfall(draws), var95)
    order = np.argsort(draws)
    lower = np.arange(draws.size) / draws.size
    upper = np.arange(1, draws.size + 1) / draws.size
    sorted_tail_weights = np.clip(upper - np.maximum(lower, 0.95), 0.0, None) / 0.05
    tail_weights = np.empty_like(sorted_tail_weights)
    tail_weights[order] = sorted_tail_weights
    contributions = [
        {
            "asset_id": item.asset_id,
            "mean_loss": float(np.mean(item.draws)),
            # Contributions are computed on the same realisations as the portfolio tail.
            "expected_shortfall_contribution": float(
                np.sum(np.asarray(item.draws, dtype=float) * tail_weights)
            ),
            "p95_standalone": float(np.percentile(item.draws, 95, method="linear")),
        }
        for item in included
    ]
    contributions.sort(key=lambda row: row["expected_shortfall_contribution"], reverse=True)
    return Aggregate(
        loss_draws=draws,
        p05=p05,
        p50=p50,
        p95=p95,
        expected_shortfall_95=portfolio_es,
        value_at_risk_95=var95,
        mean_loss=float(np.mean(draws)),
        herfindahl=herfindahl({item.asset_id: item.ead for item in losses}),
        covered_ead_share=coverage,
        included=[item.asset_id for item in included],
        excluded=excluded,
        # Descriptive only: this is not the portfolio P95.
        sum_of_individual_p95=float(
            sum(np.percentile(item.draws, 95, method="linear") for item in included)
        ),
        contributions=contributions,
        status=status,
        flags=flags,
    )


def _exclusion_reason(item: AssetLoss) -> str:
    if item.draws is None:
        return f"no loss draws ({item.status})"
    if item.status == "invalid":
        return "invalid result cannot enter portfolio arithmetic"
    if item.status == "uncalibrated":
        return "uncalibrated score is not a loss distribution"
    if item.status == "needs_review":
        return "needs_review was not approved by the aggregation policy"
    return f"status {item.status!r} is not approved for aggregation"
