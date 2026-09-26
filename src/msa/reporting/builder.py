"""The signed report, built from the run's results by the sections plugins declare.

Every number of the text is cited from the metric tree (``tree.metric_tree``) through
``ReportContext.cite``; V9 resolves each citation against the same tree. The skeleton is
common: the summary of every portfolio slice, the plugins' sections in their declared
order, the recommendations of their rules, the limitations, the assumptions and the
sources. A plugin adds what only it knows.
"""

from msa.contracts import (
    CalculationResult,
    PortfolioResult,
    PositionContext,
    Report,
    TransmissionGraph,
)

from . import wording
from .context import ReportContext, join, sentence
from .recommendations import apply, thresholds_in_force
from .tree import metric_tree


def build(
    results,
    portfolio,
    contexts,
    *,
    run_id,
    graph,
    thresholds,
    registry,
    mode="production",
    names=None,
    scenario_evidence=(),
    channel_factors=None,
    shock_labels=None,
    notes=None,
) -> Report:
    results = sorted(
        (CalculationResult.model_validate(r) for r in results), key=lambda r: r.position_id
    )
    portfolio = None if portfolio is None else PortfolioResult.model_validate(portfolio)
    contexts = [PositionContext.model_validate(c) for c in contexts]
    graph = TransmissionGraph.model_validate(graph) if graph else None
    channel_factors = channel_factors or {}
    tree_context = {"channel_factors": channel_factors}
    tree = metric_tree(results, portfolio, registry=registry, context=tree_context)
    ctx = ReportContext(
        tree=tree,
        results=results,
        portfolio=portfolio,
        registry=registry,
        names=names or {},
        channels={n.id: n.label for n in graph.nodes if n.kind == "channel"} if graph else {},
        shock_labels=shock_labels or {},
        channel_factors=channel_factors,
        notes=notes or {},
    )
    rules, defaults = thresholds_in_force(registry, thresholds)
    recommendations = [
        rec for result in results for rec in apply(result, registry, rules, tree_context)
    ]

    lines = ["### Итог", *summary(ctx)]
    types = {r.instrument_type for r in results}
    for section in sorted(registry.report_sections.values(), key=lambda s: (s.order, s.section_id)):
        if section.instrument_types and not types.intersection(section.instrument_types):
            continue
        body = section.render(ctx)
        if body:
            lines.append(f"### {section.title}")
            lines.extend(body)

    lines.append("### Рекомендации")
    by_position: dict[str, dict[str, list]] = {}
    for rec in recommendations:
        by_position.setdefault(rec.position_id, {}).setdefault(rec.rule_id, []).append(rec)
    for position_id, fired in by_position.items():
        parts = []
        for rule_id, recs in fired.items():
            actions = join(
                registry.actions[r.action].label if r.action in registry.actions else r.action
                for r in recs
            )
            spec = registry.rules.get(rule_id)
            reason = spec.label if spec else rule_id
            basis = f" ({ctx.cite(recs[0].metric_refs[0])})" if spec and spec.cite_value else ""
            parts.append(f"{actions} — {reason}{basis}")
        lines.append(f"- {ctx.position(position_id)}: " + "; ".join(parts) + ".")
    if not recommendations:
        lines.append("Не назначены.")
    if defaults:
        lines.append(
            "Пороги правил "
            + join(f"«{registry.rules[r].label}»" for r in defaults)
            + " взяты из объявления плагина: утверждённых значений в журнале порогов нет."
        )

    lines.append("### Ограничения расчёта")
    lines.extend(limitations(ctx))

    evidence = [e for edge in graph.edges for e in edge.evidence] if graph else []
    event_documents = {e.source_id for e in evidence if e.kind == "document"}
    evidence.extend(scenario_evidence)
    for result in results:
        evidence.extend(result.sources)
    keyed = {(e.kind, e.source_id, e.locator, e.fragment_sha256): e for e in evidence}
    sources = [keyed[key] for key in sorted(keyed)]
    assumptions = [e for e in sources if e.kind == "expert_assumption"]
    authors = registry.author_wording()
    lines.append("### Допущения и авторы")
    # One line per source and author, not per assumed field.
    lines.extend(
        dict.fromkeys(
            f"- {authors.get(e.author, e.author)}, источник: {source(e.source_id, registry)}"
            for e in assumptions
        )
    )
    if not assumptions:
        lines.append("Не указаны.")
    lines.append("### Источники")
    lines.extend(
        dict.fromkeys(
            "- Текст события"
            if e.source_id in event_documents
            else f"- {source(e.source_id, registry)}"
            for e in sources
        )
    )
    if not sources:
        lines.append("Не указаны.")
    return Report(
        run_id=run_id,
        summary="\n".join(lines),
        recommendations=recommendations,
        assumptions=assumptions,
        sources=sources,
        numbers=ctx.numbers,
        results=results,
        portfolio=portfolio,
        mode=mode,
    )


def source(source_id: str, registry) -> str:
    from .context import display_id

    return registry.source_wording().get(source_id) or display_id(source_id)


def summary(ctx: ReportContext) -> list[str]:
    """One paragraph per portfolio slice: its loss interval, ES95, coverage and gaps."""
    lines = []
    portfolio = ctx.portfolio
    if not ctx.results:
        return ["Событие не затрагивает позиции портфеля."]
    if portfolio is None or not portfolio.slices:
        return ["Портфельная оценка не получена: см. ограничения расчёта."]
    for slice_id, item in portfolio.slices.items():
        spec = ctx.registry.slices[slice_id]
        path = f"/portfolio/slices/{slice_id}"
        unit = unit_words(item.unit)
        if item.loss_quantiles is not None:
            lines.append(
                f"{spec.label}. {spec.measure_label} портфеля — "
                + ctx.interval(path + "/loss_quantiles", unit)
                + sentence(f"; ES95 — {ctx.cite(path + '/loss_quantiles/es95')} {unit}")
            )
        else:
            lines.append(f"{spec.label}. Оценка в деньгах не получена: см. ограничения расчёта.")
        lines.append(
            f"Расчётом охвачено {ctx.cite(path + '/covered_percent')} % "
            f"({spec.exposure_label.lower()})."
        )
        admitted = sorted(
            flag.partition(":")[2] for flag in item.flags if flag.startswith("included_by_rule:")
        )
        rules = sorted(
            flag.partition(":")[2] for flag in item.flags if flag.startswith("inclusion_rule:")
        )
        if admitted:
            lines.append(
                f"По утверждённому правилу включения {join(rules)} с раскрытием включены: "
                + ", ".join(ctx.position(p) for p in admitted)
                + "."
            )
        if item.excluded:
            lines.append(
                "Не вошли в итог среза: "
                + "; ".join(
                    f"{ctx.position(e.position_id)} — {ctx.status(e.status)}" for e in item.excluded
                )
                + "."
            )
        if item.coverage.unknown_exposure:
            lines.append(
                "Размер позиций не измерен: "
                + ", ".join(ctx.position(p) for p in item.coverage.unknown_exposure)
                + "; итог среза неполный."
            )
    if portfolio.not_aggregated:
        lines.append(
            "Не входят ни в один срез: "
            + "; ".join(
                f"{ctx.position(e.position_id)} — {ctx.status(e.status)}"
                for e in portfolio.not_aggregated
            )
            + "."
        )
    return lines


def limitations(ctx: ReportContext) -> list[str]:
    informational = frozenset().union(
        *(plugin.informational_flags for plugin in ctx.registry.plugins.values())
    )
    notes = {
        r.position_id: [f for f in r.flags if not wording.informational(f, informational)]
        for r in ctx.results
    }
    limited = [r for r in ctx.results if r.status != "ok" or notes[r.position_id]]
    everyone = len(limited) > 1 and len(limited) == len(ctx.results)
    common = (
        [
            f
            for f in notes[limited[0].position_id]
            if all(f in notes[r.position_id] for r in limited)
        ]
        if everyone
        else []
    )
    lines = []
    if common:
        lines.append(
            "Общее для всех позиций: " + "; ".join(dict.fromkeys(ctx.flag(f) for f in common)) + "."
        )
    for result in limited:
        rest = list(
            dict.fromkeys(ctx.flag(f) for f in notes[result.position_id] if f not in common)
        )
        text = f"- {ctx.position(result.position_id)} — {ctx.status(result.status)}"
        lines.append(text + (": " + "; ".join(rest) if rest else "") + ".")
    if not limited:
        lines.append("Все позиции рассчитаны без ограничений.")
    return lines


def unit_words(unit: str) -> str:
    if unit.endswith("_million"):
        currency = unit.removesuffix("_million")
        return {"RUB": "млн руб.", "USD": "млн долл.", "EUR": "млн евро"}.get(
            currency, f"млн {currency}"
        )
    return {"fraction": "", "ratio": ""}.get(unit, unit)
