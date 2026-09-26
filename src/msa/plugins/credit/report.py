"""The credit plugin's part of the report, its metric-tree view and its rules R1-R5."""

from msa.plugin_sdk import ActionSpec, RecommendationRule, ReportSection
from msa.reporting.numbers import pointer_token

from .contracts import RiskResult
from .impact import grade, impact_score

TYPES = ("corp_loan", "bond_fixed", "bond_floater", "pf_escrow", "leasing")
BREACH = 0.5
RATE_FX_FACTORS = {"credit.interest", "credit.fx"}
COVENANT_LABELS = {
    "icr": "ICR (покрытие процентов)",
    "nd_ebitda": "Чистый долг / EBITDA",
    "debt_equity": "Долг / капитал",
    "escrow_coverage": "Покрытие долга эскроу",
}


def rate_fx_share(risk: RiskResult, channel_factors: dict[str, str]) -> float | None:
    """Share of the loss change carried by rate and currency channels (Shapley, spec 14)."""
    total = sum(item.contribution for item in risk.shapley)
    if total <= 0:
        return None
    rate_fx = sum(
        item.contribution
        for item in risk.shapley
        if channel_factors.get(item.channel) in RATE_FX_FACTORS
    )
    return max(0.0, min(1.0, rate_fx / total))


def derived(risk: RiskResult, channel_factors) -> dict:
    """Values the report states that are arithmetic on one result, kept in the tree for V9."""
    values = {}
    for name in ("delta_pd", "delta_risk_score"):
        if name in risk.quantiles:
            values[f"{name}_p50_pp"] = risk.quantiles[name].p50 * 100
    share = rate_fx_share(risk, channel_factors)
    if share is not None and "delta_expected_loss" in risk.quantiles:
        values["rate_fx_channel_share"] = share
    ead = risk.credit.ead if risk.credit is not None else None
    if ead:
        loss = risk.quantiles.get("delta_expected_loss")
        price = risk.quantiles.get("position_price_change")
        gap = risk.quantiles.get("funding_gap")
        # TZ 9.3: one scale for every asset type; the project limit is its exposure.
        values["impact_score"] = impact_score(
            delta_el=loss.p50 if loss else 0.0,
            ead=ead,
            position_change=price.p50 if price else 0.0,
            deficit=gap.p50 if gap else 0.0,
            limit=ead,
        )
    return values


def tree(result, context) -> dict:
    risk = RiskResult.model_validate(result.details)
    return {
        "quantiles": {k: v.model_dump(mode="json") for k, v in risk.quantiles.items()},
        "credit": risk.credit.model_dump(mode="json") if risk.credit else {},
        "market": risk.market.model_dump(mode="json") if risk.market else {},
        "liquidity": risk.liquidity.model_dump(mode="json") if risk.liquidity else {},
        "covenants": {c.covenant_id: c.model_dump(mode="json") for c in risk.covenants},
        "shapley": {s.channel: s.model_dump(mode="json") for s in risk.shapley},
        "derived": derived(risk, context.get("channel_factors") or {}),
    }


# Sections -----------------------------------------------------------------------------


def _credit(ctx):
    return [
        (r, RiskResult.model_validate(r.details))
        for r in ctx.of_types(TYPES)
        if r.execution == "completed"
    ]


def losses(ctx) -> list[str]:
    ranked = sorted(
        (item for item in _credit(ctx) if "delta_expected_loss" in item[1].quantiles),
        key=lambda item: -item[1].quantiles["delta_expected_loss"].p50,
    )
    return [
        f"- {ctx.position(r.position_id)} — "
        + ctx.interval(f"{ctx.base(r.position_id)}/quantiles/delta_expected_loss", "млн руб.")
        for r, _ in ranked
    ]


def impact(ctx) -> list[str]:
    graded = [
        (r, risk)
        for r, risk in _credit(ctx)
        if "impact_score" in ctx.tree["positions"][r.position_id].get("derived", {})
    ]
    if not ctx.of_types(TYPES):
        return []
    lines = []
    for result, risk in sorted(
        graded,
        key=lambda item: -ctx.tree["positions"][item[0].position_id]["derived"]["impact_score"],
    ):
        score = ctx.tree["positions"][result.position_id]["derived"]["impact_score"]
        breached = any(c.breach_probability >= BREACH for c in risk.covenants)
        text = (
            f"- {ctx.position(result.position_id)}: "
            f"{ctx.cite(ctx.base(result.position_id) + '/derived/impact_score', 4)} — "
            f"{grade(score, breached)}"
        )
        lines.append(text + (", нарушение ковенанта" if breached else "") + ".")
    return lines or ["Не рассчитана."]


def channels(ctx) -> list[str]:
    credit = _credit(ctx)
    if not ctx.of_types(TYPES):
        return []
    lines = []
    for result, risk in credit:
        if not risk.shapley:
            continue
        money = "delta_expected_loss" in risk.quantiles
        parts = []
        # A channel that does not reach the position contributes nothing and is not listed.
        reached = [item for item in risk.shapley if item.contribution != 0]
        for item in sorted(reached, key=lambda item: -item.contribution):
            path = (
                f"{ctx.base(result.position_id)}/shapley/{pointer_token(item.channel)}/contribution"
            )
            value = ctx.cite(path) + " млн руб." if money else ctx.cite(path, 4)
            parts.append(f"{ctx.channel(item.channel)} — {value}")
        if not parts:
            continue
        label = "" if money else " (вклад в изменение риск-скора)"
        lines.append(f"- {ctx.position(result.position_id)}{label}: " + "; ".join(parts))
    return lines or ["Вклад каналов не рассчитан."]


def covenants(ctx) -> list[str]:
    if not ctx.of_types(TYPES):
        return []
    lines = []
    for result, risk in _credit(ctx):
        for item in sorted(risk.covenants, key=lambda c: -c.breach_probability):
            if item.breach_probability < BREACH:
                continue
            path = f"{ctx.base(result.position_id)}/covenants/{pointer_token(item.covenant_id)}"
            name = COVENANT_LABELS.get(item.metric) or item.covenant_id
            lines.append(
                f"- {ctx.position(result.position_id)}, {name}: "
                f"вероятность нарушения {ctx.cite(path + '/breach_probability')}, "
                f"минимальный запас {ctx.cite(path + '/min_headroom')}."
            )
    return lines or ["Не выявлены."]


def bonds(ctx) -> list[str]:
    return [
        f"- {ctx.position(r.position_id)}: изменение стоимости позиции "
        + ctx.interval(f"{ctx.base(r.position_id)}/quantiles/position_price_change", "млн руб.")
        + f"; спред-дюрация {ctx.cite(ctx.base(r.position_id) + '/market/duration')}."
        for r, risk in _credit(ctx)
        if "position_price_change" in risk.quantiles
    ]


def liquidity(ctx) -> list[str]:
    return [
        f"- {ctx.position(r.position_id)}: дефицит финансирования на конец горизонта "
        + ctx.interval(f"{ctx.base(r.position_id)}/quantiles/funding_gap", "млн руб.")
        + "."
        for r, risk in _credit(ctx)
        if "funding_gap" in risk.quantiles and risk.quantiles["funding_gap"].p95 > 0
    ]


def calibration_note(ctx) -> list[str]:
    registry = ctx.notes.get("credit")
    if not ctx.of_types(TYPES) or not registry:
        return []
    if registry["registry_id"] == "none":
        return ["Калибровка PD не загружена: вероятностный выход — риск-скор, не PD."]
    from msa.reporting.numbers import extract_numbers

    note = registry["note"] if not extract_numbers(registry["note"]) else ""
    name = (
        "синтетическая демо-калибровка"
        if registry.get("kind") == "synthetic_demo"
        else (registry["registry_id"] if not extract_numbers(registry["registry_id"]) else "банка")
    )
    return [f"Калибровка PD — {name}. {note}".rstrip()]


SECTIONS = (
    ReportSection("credit.losses", "Рост ожидаемых потерь по позициям", 10, losses, TYPES),
    ReportSection("credit.impact", "Степень воздействия", 20, impact, TYPES),
    ReportSection("credit.channels", "Каналы влияния", 30, channels, TYPES),
    ReportSection("credit.covenants", "Ковенанты под угрозой", 40, covenants, TYPES),
    ReportSection("credit.bonds", "Облигации", 50, bonds, TYPES),
    ReportSection("credit.liquidity", "Ликвидность", 60, liquidity, TYPES),
    ReportSection("credit.calibration", "Калибровка PD", 90, calibration_note, TYPES),
)


# Rules R1-R5 (TZ 3.6) -----------------------------------------------------------------


def _risk(result):
    if result.plugin_id != "credit" or result.execution != "completed":
        return None
    return RiskResult.model_validate(result.details)


def _base(result):
    return "/positions/" + pointer_token(result.position_id)


def observe_icr(result, context):
    risk = _risk(result)
    if risk is None or "icr" not in risk.quantiles:
        return None
    return risk.quantiles["icr"].p50, f"{_base(result)}/quantiles/icr/p50"


def observe_breach(result, context):
    risk = _risk(result)
    if risk is None or not risk.covenants:
        return None
    worst = max(risk.covenants, key=lambda c: (c.breach_probability, c.covenant_id))
    return (
        worst.breach_probability,
        f"{_base(result)}/covenants/{pointer_token(worst.covenant_id)}/breach_probability",
    )


def observe_delta_pd(result, context):
    # R3 reads the PD change; without a calibrated PD, the change of the risk score (TZ 3.6).
    risk = _risk(result)
    if risk is None:
        return None
    for name in ("delta_pd", "delta_risk_score"):
        if name in risk.quantiles:
            return risk.quantiles[name].p50 * 100, f"{_base(result)}/derived/{name}_p50_pp"
    return None


def observe_rate_fx(result, context):
    risk = _risk(result)
    if risk is None or "delta_expected_loss" not in risk.quantiles:
        return None
    share = rate_fx_share(risk, context.get("channel_factors") or {})
    if share is None:
        return None
    return share, f"{_base(result)}/derived/rate_fx_channel_share"


def observe_delta_el(result, context):
    risk = _risk(result)
    if risk is None or "delta_expected_loss" not in risk.quantiles:
        return None
    return (
        risk.quantiles["delta_expected_loss"].p50,
        f"{_base(result)}/quantiles/delta_expected_loss/p50",
    )


OBSERVATIONS = {
    "credit.icr_p50": observe_icr,
    "credit.covenant_breach_probability": observe_breach,
    "credit.delta_pd_p50": observe_delta_pd,
    "credit.rate_fx_channel_share": observe_rate_fx,
    "credit.delta_el_p50": observe_delta_el,
}

RULES = (
    RecommendationRule(
        "credit.R1",
        "покрытие процентов по медиане ниже порога",
        "credit.icr_p50",
        "lt",
        1.0,
        ("restructure",),
        unit="ratio",
        cite_value=True,
    ),
    RecommendationRule(
        "credit.R2",
        "вероятность нарушения ковенанта достигла порога",
        "credit.covenant_breach_probability",
        "ge",
        0.5,
        ("add_collateral", "covenant_talks"),
        unit="fraction",
    ),
    RecommendationRule(
        "credit.R3",
        "рост вероятности дефолта по медиане достиг порога",
        "credit.delta_pd_p50",
        "ge",
        5.0,
        ("limit_cut",),
        unit="percentage_point",
        cite_value=True,
    ),
    RecommendationRule(
        "credit.R4",
        "основная часть роста потерь идёт через ставку и курс",
        "credit.rate_fx_channel_share",
        "ge",
        0.5,
        ("hedge",),
        unit="fraction",
    ),
    RecommendationRule(
        "credit.R5",
        "ожидаемые потери растут, более жёсткие правила не сработали",
        "credit.delta_el_p50",
        "gt",
        0.0,
        ("watchlist",),
        unit="RUB_million",
        fallback_only=True,
    ),
)

ACTIONS = (
    ActionSpec("restructure", "реструктуризировать долг"),
    ActionSpec("add_collateral", "запросить дополнительное обеспечение"),
    ActionSpec("covenant_talks", "провести переговоры по ковенантам"),
    ActionSpec("limit_cut", "сократить лимит"),
    ActionSpec("hedge", "хеджировать процентный и валютный риск"),
    ActionSpec("watchlist", "включить в список наблюдения"),
)
