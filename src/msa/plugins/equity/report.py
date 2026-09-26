"""The equity plugin's part of the report, its metric-tree view and its rules."""

from msa.plugin_sdk import ActionSpec, RecommendationRule, ReportSection
from msa.reporting.context import sentence
from msa.reporting.numbers import extract_numbers, pointer_token

from .schemas import ShareDetails

TYPES = ("common_stock",)


def _key(factor_id, key):
    return f"{factor_id}:{key}" if key else factor_id


def tree(result, context) -> dict:
    details = ShareDetails.model_validate(result.details)
    loss = result.metrics["equity.loss"].quantiles
    derived = {}
    if details.value_current > 0 and loss is not None:
        derived["loss_p95_share_pct"] = loss.p95 / details.value_current * 100
    return {
        "factors": {
            _key(item.factor_id, item.key): {"contribution": item.contribution, "label": item.label}
            for item in details.factor_contributions
        },
        "central": details.central.model_dump(mode="json"),
        "derived": derived,
    }


def _shares(ctx):
    return [r for r in ctx.of_types(TYPES) if r.execution == "completed"]


def results(ctx) -> list[str]:
    lines = []
    for result in sorted(_shares(ctx), key=lambda r: -(r.metrics["equity.loss"].quantiles.p50)):
        pid = result.position_id
        unit = "млн руб." if result.base_currency == "RUB" else f"млн {result.base_currency}"
        lines.append(
            f"- {ctx.position(pid)}: результат к текущей стоимости "
            + ctx.interval(ctx.metric_path(pid, "equity.pnl"), unit)
            + "; к базовому сценарию — "
            + ctx.cite(ctx.metric_path(pid, "equity.pnl_vs_base") + "/p50")
            + f" {unit} по медиане; потери P95 — "
            + ctx.cite(ctx.metric_path(pid, "equity.loss") + "/p95")
            + f" {unit}, ES95 — "
            + sentence(ctx.cite(ctx.metric_path(pid, "equity.loss") + "/es95") + f" {unit}")
        )
    return lines


def factors(ctx) -> list[str]:
    lines = []
    for result in _shares(ctx):
        details = ShareDetails.model_validate(result.details)
        parts = []
        for item in details.factor_contributions:
            if item.contribution == 0:
                continue
            key = _key(item.factor_id, item.key)
            path = f"{ctx.base(result.position_id)}/factors/{pointer_token(key)}/contribution"
            where = f" ({item.key})" if item.key and not extract_numbers(item.key) else ""
            parts.append(f"{item.label}{where} — {ctx.cite(path)}")
        if parts:
            lines.append(f"- {ctx.position(result.position_id)}: " + "; ".join(parts) + ".")
    return lines


SECTIONS = (
    ReportSection("equity.results", "Рыночный результат по акциям", 70, results, TYPES),
    ReportSection(
        "equity.factors", "Вклад рыночных факторов в центральном сценарии", 75, factors, TYPES
    ),
)


def observe_loss_share(result, context):
    if result.plugin_id != "equity" or result.execution != "completed":
        return None
    details = ShareDetails.model_validate(result.details)
    loss = result.metrics["equity.loss"].quantiles
    if details.value_current <= 0 or loss is None:
        return None
    base = "/positions/" + pointer_token(result.position_id)
    return loss.p95 / details.value_current * 100, f"{base}/derived/loss_p95_share_pct"


def observe_pnl(result, context):
    if result.plugin_id != "equity" or result.execution != "completed":
        return None
    base = "/positions/" + pointer_token(result.position_id)
    return (
        result.metrics["equity.pnl"].quantiles.p50,
        f"{base}/metrics/{pointer_token('equity.pnl')}/p50",
    )


OBSERVATIONS = {
    "equity.loss_p95_share": observe_loss_share,
    "equity.pnl_p50": observe_pnl,
}

RULES = (
    RecommendationRule(
        "equity.E1",
        "потери P95 превышают порог доли стоимости позиции",
        "equity.loss_p95_share",
        "ge",
        20.0,
        ("equity_hedge",),
        unit="percentage_point",
        cite_value=True,
    ),
    RecommendationRule(
        "equity.E2",
        "медианный результат отрицательный, более жёсткое правило не сработало",
        "equity.pnl_p50",
        "lt",
        0.0,
        ("equity_watch",),
        unit="base_money",
        fallback_only=True,
    ),
)

ACTIONS = (
    ActionSpec("equity_hedge", "захеджировать рыночный риск позиции или сократить её"),
    ActionSpec("equity_watch", "включить позицию в список наблюдения"),
)
