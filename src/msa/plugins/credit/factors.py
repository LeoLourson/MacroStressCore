"""The seven drivers of the credit families as registered factors of the ``graph`` scope.

A shock of one of them enters at a channel of the event's graph and reaches a borrower
through its sector; the families read them as monthly changes (spec 3.1).
"""

from msa.plugin_sdk import FactorSpec

from .family import factor_id


def _relative(driver, label, description):
    return FactorSpec(
        factor_id=factor_id(driver),
        label=label,
        unit="fraction",
        scope="graph",
        application="relative",
        quantity="relative_change",
        temporal="monthly_path",
        description=description,
        lower_bound=-1.0,
    )


FACTORS: tuple[FactorSpec, ...] = (
    _relative("revenue", "Выручка", "Цены, объём продаж, новый бизнес."),
    _relative("cogs", "Себестоимость", "Закупки, импорт, сборы на закупаемые товары."),
    _relative("logistics", "Логистические расходы", "Стоимость перевозки и маршрутов."),
    FactorSpec(
        factor_id=factor_id("working_capital"),
        label="Оборотный капитал",
        unit="days",
        scope="graph",
        application="additive",
        quantity="days",
        temporal="monthly_path",
        description="Задержка расчётов, рост запасов и дебиторской задолженности, в днях.",
    ),
    FactorSpec(
        factor_id=factor_id("interest"),
        label="Процентные расходы",
        unit="fraction",
        scope="graph",
        application="additive",
        quantity="rate_annual",
        temporal="monthly_path",
        description="Изменение стоимости долга в годовых пунктах ставки (0,02 — плюс 2 п.п.).",
    ),
    _relative("capex", "Капитальные затраты", "Собственные инвестиции компании."),
    _relative("fx", "Валютный курс", "Переоценка валютных затрат заёмщика."),
)

BY_ID = {spec.factor_id: spec for spec in FACTORS}
