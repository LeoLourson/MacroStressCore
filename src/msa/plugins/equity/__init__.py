"""Equity plugin: ordinary shares, long positions, a factor stress on the horizon.

One instrument type (``common_stock``), one model (``equity.factor_stress.v1``), two factors
of its own — the market (``equity.market``, keyed by index) and the sector
(``equity.sector``, through the event's graph by the issuer's OKVED) — and the shared
``market.fx``; its P&L enters the ``market.pnl`` slice.
Sensitivities are loaded with the data snapshot, each with its author and source; there is
no automatic calibration yet.
"""

from msa.plugin_sdk import (
    BASE_MONEY,
    FactorSpec,
    InstrumentTypeSpec,
    MetricSpec,
    Plugin,
    ResultView,
    SnapshotKindSpec,
    ViewBlock,
)

from .demo import cases
from .editor import EDITOR, from_draft
from .model import MODEL_ID, PLUGIN_ID, PLUGIN_VERSION, SECTOR_FACTOR, ShareFactorStress
from .report import ACTIONS, OBSERVATIONS, RULES, SECTIONS, TYPES, tree
from .schemas import DIVIDEND, SCHEMA_VERSION, SENSITIVITY, SharePosition, ShareTerms

M = BASE_MONEY

plugin = Plugin(
    plugin_id=PLUGIN_ID,
    version=PLUGIN_VERSION,
    sdk=">=1.0,<2.0",
    label="Акции (факторный стресс)",
    description="Обыкновенные акции, длинные позиции, стресс рыночного, отраслевого и "
    "валютного факторов на горизонте.",
    instrument_types=(
        InstrumentTypeSpec(
            type_id="common_stock",
            label="Обыкновенная акция",
            terms_schema=ShareTerms,
            position_schema=SharePosition,
            default_model=MODEL_ID,
            schema_version=SCHEMA_VERSION,
            description="Длинная позиция в обыкновенных акциях одного эмитента.",
            issuer_required=True,
            identity="ticker",
            editor=EDITOR,
            from_draft=from_draft,
        ),
    ),
    models=(ShareFactorStress(),),
    metrics=(
        MetricSpec(
            "equity.value_current",
            "Стоимость позиции на дату оценки",
            M,
            kind="value",
            period="as_of",
        ),
        MetricSpec(
            "equity.value_horizon",
            "Стоимость позиции на конец горизонта",
            M,
            direction="lower_is_worse",
        ),
        MetricSpec(
            "equity.pnl",
            "Результат к текущей стоимости (с дивидендами)",
            M,
            direction="lower_is_worse",
        ),
        MetricSpec(
            "equity.pnl_vs_base", "Результат к базовому сценарию", M, direction="lower_is_worse"
        ),
        MetricSpec(
            "equity.loss",
            "Потери стоимости позиции",
            M,
            direction="higher_is_worse",
            aggregation="sum_by_realisation",
            description="Минус результат к текущей стоимости; ES95 — средние потери "
            "худших пяти процентов сценариев.",
        ),
        MetricSpec(
            "equity.dividends",
            "Дивиденды за горизонт в центральном сценарии",
            M,
            kind="value",
            period="horizon",
        ),
        MetricSpec(
            "equity.log_return",
            "Логарифмическая доходность цены",
            "log_return",
            direction="lower_is_worse",
            decimals=4,
        ),
    ),
    factors=(
        FactorSpec(
            factor_id="equity.market",
            label="Рынок акций",
            unit="log_return",
            scope="global",
            application="log",
            quantity="log_return",
            key_label="индекс рынка, например MOEX",
            description="Логарифмическое изменение индекса рынка акций к концу горизонта.",
        ),
        SECTOR_FACTOR,
    ),
    snapshot_kinds=(
        SnapshotKindSpec(
            kind=SENSITIVITY,
            label="Чувствительности акции",
            subject="идентификатор инструмента",
            values={
                "beta_market": "бета к индексу рынка",
                "beta_sector": "бета к отраслевому фактору",
                "residual_volatility": "остаточная волатильность за год, доля",
            },
        ),
        SnapshotKindSpec(
            kind=DIVIDEND,
            label="Дивиденды на горизонт",
            subject="идентификатор инструмента",
            values={"amount": "сумма на акцию за горизонт, в валюте акции"},
        ),
    ),
    views=(
        ResultView(
            view_id="equity.position",
            instrument_types=TYPES,
            component="equity.position",
            # The loss is the result with the opposite sign: a second column would mirror it.
            summary_metrics=("equity.pnl",),
            blocks=(
                ViewBlock(
                    kind="metrics",
                    title="Итог на конец горизонта",
                    metric_ids=(
                        "equity.value_current",
                        "equity.value_horizon",
                        "equity.pnl",
                        "equity.pnl_vs_base",
                        "equity.loss",
                        "equity.dividends",
                    ),
                ),
                ViewBlock(
                    kind="histogram",
                    title="Распределение потерь",
                    path="/loss_histogram",
                    metric_ids=("equity.loss",),
                ),
                ViewBlock(
                    kind="table",
                    title="Вклад факторов в центральном сценарии",
                    path="/factor_contributions",
                    columns=(("label", "Фактор"), ("key", "Ключ"), ("contribution", "Вклад")),
                ),
                ViewBlock(kind="sources", title="Источники данных"),
            ),
            labels={
                "price": "Цена акции",
                "fx": "Курс к базовой валюте",
                "quantity": "Количество акций",
                "beta_market": "Бета к рынку",
                "beta_sector": "Бета к отрасли",
                "residual_sigma": "Остаточный риск на горизонте",
                "dividend_per_share": "Дивиденды на акцию",
                # Keys of the report tree (report.tree); "" leaves a grouping key out of a
                # path's description.
                "derived": "",
                "contribution": "",
                "factors": "вклад фактора",
                "loss_p95_share_pct": "Потери P95 в доле стоимости позиции",
            },
        ),
    ),
    report_sections=SECTIONS,
    observations=OBSERVATIONS,
    rules=RULES,
    actions=ACTIONS,
    flags={
        "dividends_at_horizon_fx": "дивиденды пересчитаны по курсу конца горизонта",
        "residual_declared_zero": "остаточный риск акции не учитывается (задано явно)",
        "price_stale": "цена акции устарела",
        "calibration_mismatch": "чувствительности оценены к другому индексу или отрасли",
        "sensitivity_without_author": "у экспертной чувствительности нет автора",
        "dividends_not_declared": "дивиденды на горизонт не заданы",
        "dividend_horizon_mismatch": "дивиденды заданы на другой горизонт",
        "dividend_invalid": "дивиденды заданы некорректно",
        "price_invalid": "цена акции некорректна",
        "residual_volatility_invalid": "остаточная волатильность вне допустимых пределов",
        "price_currency_mismatch": "цена задана не в валюте акции",
        "fx_invalid": "курс валюты некорректен",
        "sensitivity_missing:": "не задана чувствительность «{}»",
        "missing_pre_horizon_history": "нет истории до начала горизонта",
    },
    informational_flags=frozenset({"dividends_at_horizon_fx", "missing_pre_horizon_history"}),
    sources={
        "demo:market": "рыночные данные демо-снимка",
        "demo:equity-sensitivities": "экспертные чувствительности акций демо-стенда",
    },
    authors={
        "demo:market-desk": "аналитик рынка демо-стенда",
        "demo:data-desk": "составитель демо-данных",
    },
    tree=tree,
    demo=cases,
)
