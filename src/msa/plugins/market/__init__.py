"""Shared market declarations: the exchange-rate factor and the market P&L slice.

Every family priced at market — equities now, funds, commodities and derivatives later —
contributes to the same ``market.pnl`` slice and reads the same ``market.fx`` factor, so
their realisations add up in one currency and one scenario set.
"""

from msa.contracts.snapshot import FX_RATE, PRICE
from msa.plugin_sdk import BASE_MONEY, FactorSpec, Plugin, SliceSpec, SnapshotKindSpec

plugin = Plugin(
    plugin_id="market",
    version="1.0.0",
    sdk=">=1.0,<2.0",
    label="Рыночные факторы",
    description="Валютный фактор и портфельный срез рыночного результата.",
    factors=(
        FactorSpec(
            factor_id="market.fx",
            label="Изменение валютного курса",
            unit="log_return",
            scope="currency_pair",
            application="log",
            quantity="log_return",
            key_label="Валютная пара «валюта/базовая», например USD/RUB",
            description="Логарифмическое изменение цены единицы валюты в базовой валюте "
            "к концу горизонта.",
        ),
    ),
    slices=(
        SliceSpec(
            slice_id="market.pnl",
            label="Рыночный результат",
            measure_label="Рыночные потери",
            exposure_basis="market_value",
            exposure_label="Стоимость позиций",
            unit=BASE_MONEY,
            description="Потери стоимости позиций (с доходами за горизонт) относительно "
            "текущей стоимости; прибыль — отрицательные потери.",
        ),
    ),
    snapshot_kinds=(
        SnapshotKindSpec(
            kind=FX_RATE,
            label="Валютный курс",
            subject="валютная пара USD/RUB",
            values={"rate": "единиц базовой валюты за единицу валюты"},
        ),
        SnapshotKindSpec(
            kind=PRICE,
            label="Цена инструмента",
            subject="идентификатор инструмента",
            values={"price": "в валюте инструмента за единицу"},
        ),
    ),
    flags={
        "factor_not_in_scenario:": "сценарий не задаёт фактор «{}»: он не шокирован",
        "fx_missing:": "нет курса {} на дату оценки",
    },
    informational_flags=frozenset({"factor_not_in_scenario:"}),
)
