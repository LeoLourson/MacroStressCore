"""Reading a run's outcome, and the verdict of one common-sense check."""

import math
from dataclasses import dataclass, field

from .line import Outcome


@dataclass
class Verdict:
    """``ok``: True — the system behaves as common sense expects; False — it does not;
    None — the run could not answer the question (reported, never counted as a pass)."""

    ok: bool | None
    observed: str
    numbers: dict = field(default_factory=dict)


def result(outcome: Outcome, position_id: str) -> dict | None:
    return outcome.results.get(position_id)


def metric(outcome: Outcome, position_id: str, metric_id: str, q: str = "p50"):
    """A quantile (``p05``, ``p50``, ``p95``, ``es95``) or the central ``value`` of a metric."""
    item = result(outcome, position_id)
    if item is None:
        return None
    value = (item.get("metrics") or {}).get(metric_id)
    if value is None:
        return None
    if q == "value":
        return value.get("value")
    return (value.get("quantiles") or {}).get(q)


def delta_el(outcome, position_id, q="p50"):
    return metric(outcome, position_id, "credit.delta_expected_loss", q)


def equity_loss(outcome, position_id, q="p50"):
    return metric(outcome, position_id, "equity.loss", q)


def series(outcome, position_id, trajectory: str, name: str) -> list | None:
    """A credit position's monthly series of the ``base`` or ``stress`` trajectory."""
    item = result(outcome, position_id)
    if item is None or not item.get("details"):
        return None
    found = item["details"].get(trajectory, {}).get("series", {}).get(name)
    return None if found is None else found["values"]


def pd_base(outcome, position_id):
    values = series(outcome, position_id, "base", "risk_score")
    return None if values is None else values[-1]


def pd_stress(outcome, position_id):
    return metric(outcome, position_id, "credit.pd", "value")


def revenue_change(outcome, position_id):
    """Stress over base revenue in the last month of the horizon, minus one."""
    base = series(outcome, position_id, "base", "revenue")
    stress = series(outcome, position_id, "stress", "revenue")
    if not base or not stress:
        return None
    return stress[-1] / base[-1] - 1.0


def slice_q(outcome: Outcome, slice_id: str, q: str = "p95"):
    item = (outcome.portfolio or {}).get("slices", {}).get(slice_id)
    if item is None or item.get("loss_quantiles") is None:
        return None
    return item["loss_quantiles"][q]


def slice_item(outcome: Outcome, slice_id: str) -> dict | None:
    return (outcome.portfolio or {}).get("slices", {}).get(slice_id)


def recommendations(outcome: Outcome, position_id: str | None = None) -> list[str]:
    report = outcome.report or {}
    return sorted(
        f"{item['rule_id']}:{item['action']}"
        for item in report.get("recommendations", [])
        if position_id is None or item["position_id"] == position_id
    )


def close(a, b, *, rel=1e-9, abs_=1e-9) -> bool:
    return a is not None and b is not None and math.isclose(a, b, rel_tol=rel, abs_tol=abs_)


def increasing(values, *, strict=True) -> bool:
    if any(v is None for v in values):
        return False
    pairs = list(zip(values, values[1:], strict=False))
    return all(b > a for a, b in pairs) if strict else all(b >= a for a, b in pairs)


def decreasing(values, *, strict=True) -> bool:
    return increasing([-v if v is not None else None for v in values], strict=strict)


def fmt(value, digits=4) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}g}"
    return str(value)


def why_not_calculated(outcome: Outcome, position_id: str) -> str:
    if outcome.error:
        return "ошибка прогона: " + outcome.error
    if outcome.blocked:
        failed = [v["message"] for v in outcome.blocked if not v.get("ok", False)]
        return "сценарий не принят: " + "; ".join(failed)
    if position_id not in outcome.reached:
        return "позиция не достигнута событием"
    item = result(outcome, position_id) or {}
    return f"{item.get('execution')}/{item.get('status')}: " + ", ".join(item.get("flags") or [])
