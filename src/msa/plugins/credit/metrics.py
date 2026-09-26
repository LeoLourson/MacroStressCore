"""Metrics of the credit models, their slice and their instrument types for the catalog."""

from msa.plugin_sdk import InstrumentTypeSpec, MetricSpec, SliceSpec

from .families import FAMILIES
from .schemas import SCHEMA_VERSION, CreditPosition, terms_for

M = "RUB_million"

METRICS: tuple[MetricSpec, ...] = (
    MetricSpec(
        "credit.delta_expected_loss",
        "Рост ожидаемых потерь",
        M,
        direction="higher_is_worse",
        aggregation="sum_by_realisation",
        description="ΔEL = EL(стресс) − EL(база) за горизонт, по совместным реализациям.",
    ),
    MetricSpec(
        "credit.expected_loss",
        "Ожидаемые потери в центральном сценарии",
        M,
        kind="value",
        period="horizon",
        direction="higher_is_worse",
    ),
    MetricSpec(
        "credit.pd",
        "PD на конец горизонта (центральный сценарий)",
        "fraction",
        kind="value",
        direction="higher_is_worse",
        decimals=4,
    ),
    MetricSpec(
        "credit.risk_score",
        "Индекс риска (без калибровки PD)",
        "fraction",
        kind="value",
        direction="higher_is_worse",
        decimals=4,
    ),
    MetricSpec(
        "credit.pd_horizon",
        "PD на конец горизонта",
        "fraction",
        direction="higher_is_worse",
        decimals=4,
    ),
    MetricSpec(
        "credit.risk_score_horizon",
        "Индекс риска на конец горизонта",
        "fraction",
        direction="higher_is_worse",
        decimals=4,
    ),
    MetricSpec("credit.delta_pd", "Рост PD", "fraction", direction="higher_is_worse", decimals=4),
    MetricSpec(
        "credit.delta_risk_score",
        "Рост индекса риска",
        "fraction",
        direction="higher_is_worse",
        decimals=4,
    ),
    MetricSpec(
        "credit.icr",
        "Покрытие процентов (ICR) на конец горизонта",
        "ratio",
        direction="lower_is_worse",
    ),
    MetricSpec(
        "credit.funding_gap",
        "Дефицит финансирования на конец горизонта",
        M,
        direction="higher_is_worse",
    ),
    MetricSpec(
        "credit.escrow_coverage",
        "Покрытие долга эскроу на конец горизонта",
        "ratio",
        direction="lower_is_worse",
    ),
    MetricSpec(
        "credit.debt_equity",
        "Долг / капитал на конец горизонта",
        "ratio",
        direction="higher_is_worse",
    ),
    MetricSpec(
        "credit.position_price_change",
        "Изменение стоимости облигации",
        M,
        direction="lower_is_worse",
    ),
    MetricSpec("credit.ead", "Сумма под риском (EAD)", M, kind="value", period="as_of"),
    MetricSpec(
        "credit.lgd",
        "Потери при дефолте (LGD)",
        "fraction",
        kind="value",
        period="as_of",
        decimals=4,
    ),
)

SLICES = (
    SliceSpec(
        slice_id="credit.loss",
        label="Кредитные потери",
        measure_label="Рост ожидаемых потерь",
        exposure_basis="ead",
        exposure_label="Сумма под риском (EAD)",
        description="Рост ожидаемых кредитных потерь за горизонт по совместным реализациям.",
    ),
)


def instrument_types(editor, from_draft) -> tuple[InstrumentTypeSpec, ...]:
    return tuple(
        InstrumentTypeSpec(
            type_id=type_id,
            label=label,
            terms_schema=terms_for(family),
            position_schema=CreditPosition,
            default_model=family.model_id,
            schema_version=SCHEMA_VERSION,
            description=type(family).__doc__.strip().splitlines()[0]
            if type(family).__doc__
            else "",
            editor=editor(family),
            from_draft=from_draft,
        )
        for family in FAMILIES
        for type_id, label in family.types.items()
    )
