"""Operating companies (spec 5): a borrower whose debt is serviced from its operating cash.

Reported annual figures are spread evenly across the months; that reading is flagged. Price
reacts to unit costs through the pass-through share and the demand elasticity (spec 4).
"""

import numpy as np

from ..family import CovenantMetric, CreditFamily, Evaluation, Inputs, Series, compound
from ..family import InputField as F
from ..math import metrics, pricing
from ..math.credit import corporate_features
from ..math.operating import SIMPLIFIED_TAX_FLAG, DebtTranche, OperatingBase, OperatingShocks
from ..math.operating import run as run_operating

ANNUAL_FINANCIALS_FLAG = "annual_financials_spread_evenly"
ASSUMED_WORKING_CAPITAL_FLAG = "assumed_working_capital_days"
INVALID_ELASTICITY_FLAG = "demand_elasticity_missing_or_invalid"
FX_WITHOUT_IMPORT_FLAG = "fx_without_import_share"

MONTHS = 12
M = "RUB_million"

OPERATING_FIELDS: tuple[F, ...] = (
    F("revenue", M, "Выручка за год", required=True),
    F("cogs", M, "Себестоимость за год", required=True),
    F("net_debt", M, "Чистый долг", required=True),
    F("borrowing_rate", "fraction", "Ставка по долгу", required=True),
    F("opex", M, "Операционные расходы за год", default=0.0),
    F("opex_variable_share", "fraction", "Доля переменных операционных расходов", default=0.0),
    F("cash", M, "Денежные средства", default=0.0),
    F(
        "dso",
        "days",
        "Оборачиваемость дебиторской задолженности",
        default=45.0,
        assumption=ASSUMED_WORKING_CAPITAL_FLAG,
        hint="без неё — 45 дней по допущению",
        minimum=0.0,
    ),
    F(
        "dio",
        "days",
        "Оборачиваемость запасов",
        default=30.0,
        assumption=ASSUMED_WORKING_CAPITAL_FLAG,
        hint="без неё — 30 дней по допущению",
        minimum=0.0,
    ),
    F(
        "dpo",
        "days",
        "Оборачиваемость кредиторской задолженности",
        default=30.0,
        assumption=ASSUMED_WORKING_CAPITAL_FLAG,
        hint="без неё — 30 дней по допущению",
        minimum=0.0,
    ),
    F(
        "tax_rate",
        "fraction",
        "Ставка налога на прибыль",
        default=0.20,
        assumption="assumed_tax_rate",
        hint="без неё — 20 % по допущению",
    ),
    F(
        "demand_elasticity",
        "ratio",
        "Эластичность спроса по цене",
        default=-1.0,
        assumption="assumed_demand_elasticity",
        hint="отрицательное число, например −1,25; без неё — −1 по допущению",
        maximum=0.0,
    ),
    F(
        "pass_through",
        "fraction",
        "Доля переноса затрат в цену",
        default=0.0,
        assumption="assumed_no_pass_through",
        hint="без неё рост затрат в цену не переносится",
    ),
    F(
        "gross_debt",
        M,
        "Валовый долг",
        hint="без него — чистый долг плюс денежные средства",
        advanced=True,
    ),
    F("margin", "fraction", "Маржа к ставке", default=0.0, advanced=True),
    F("rate_floor", "fraction", "Нижняя граница ставки", advanced=True),
    F("rate_cap", "fraction", "Верхняя граница ставки", advanced=True),
    F("scheduled_amortisation", M, "Плановое погашение долга за год", default=0.0, advanced=True),
    F("credit_limit", M, "Лимит возобновляемой линии", advanced=True),
    F("revolver_drawn", M, "Выборка по возобновляемой линии", default=0.0, advanced=True),
    F("revolver_margin", "fraction", "Маржа по возобновляемой линии", default=0.0, advanced=True),
    F(
        "fixed_production_cost",
        M,
        "Постоянные производственные затраты за год",
        default=0.0,
        advanced=True,
    ),
    F("other_operating_income", M, "Прочие операционные доходы за год", default=0.0, advanced=True),
    F("other_current_assets", M, "Прочие оборотные активы", default=0.0, advanced=True),
    F(
        "other_current_liabilities",
        M,
        "Прочие краткосрочные обязательства",
        default=0.0,
        advanced=True,
    ),
    F("capex", M, "Поддерживающий capex за год", default=0.0, advanced=True),
    F("growth_capex", M, "Capex развития за год", default=0.0, advanced=True),
    F("dividend", M, "Дивиденды за год", default=0.0, advanced=True),
    F("cash_floor", M, "Неснижаемый остаток денежных средств", default=0.0, advanced=True),
    F("restricted_cash", M, "Ограниченные денежные средства", default=0.0, advanced=True),
)

OPERATING_SERIES: tuple[Series, ...] = (
    Series("revenue", "Выручка"),
    Series("variable_cost", "Переменные затраты"),
    Series("opex", "Операционные расходы"),
    Series("ebitda", "EBITDA"),
    Series("accounts_receivable", "Дебиторская задолженность", kind="stock_money"),
    Series("inventory", "Запасы", kind="stock_money"),
    Series("accounts_payable", "Кредиторская задолженность", kind="stock_money"),
    Series("net_working_capital", "Оборотный капитал", kind="stock_money"),
    Series("cfads", "Денежный поток до финансирования"),
    Series("interest", "Проценты"),
    Series("debt", "Долг", kind="stock_money"),
    Series("cash", "Денежные средства", kind="stock_money"),
    Series("net_debt", "Чистый долг", kind="stock_money"),
    Series("funding_gap", "Дефицит финансирования", kind="stock_money"),
    Series("cash_headroom", "Запас ликвидности", kind="stock_money"),
    Series("icr", "Покрытие процентов (ICR)", unit="ratio", kind="ratio"),
    Series("nd_ebitda", "Чистый долг / EBITDA", unit="ratio", kind="ratio"),
)


class OperatingCompany(CreditFamily):
    """The monthly operating and cash model shared by loans and bonds of operating companies."""

    segment = "corporate"
    fields = OPERATING_FIELDS
    disclosure = (
        "revenue",
        "cogs",
        "opex",
        "net_debt",
        "borrowing_rate",
        "cash",
        "dso",
        "dio",
        "dpo",
        "tax_rate",
        "demand_elasticity",
        "pass_through",
    )
    series = OPERATING_SERIES
    covenant_metrics = (
        CovenantMetric("icr", "ICR (покрытие процентов)", "ge", 2.0),
        CovenantMetric("nd_ebitda", "Чистый долг / EBITDA", "le", 3.0),
    )
    decision_metrics = ("icr", "funding_gap")
    review_flags = frozenset(
        {ANNUAL_FINANCIALS_FLAG, ASSUMED_WORKING_CAPITAL_FLAG, SIMPLIFIED_TAX_FLAG}
    )

    def evaluate(self, inputs: Inputs, calendar, drivers) -> Evaluation:
        flags: list[str] = []
        base = self.base(inputs, flags)
        # A currency shock moves only the imported part of the costs.
        fx = np.asarray(drivers["fx"], dtype=float)
        if inputs.import_share == 0 and np.any(fx != 0):
            flags.append(FX_WITHOUT_IMPORT_FLAG)
        unit_cost = compound(drivers["cogs"], drivers["logistics"], inputs.import_share * fx)
        revenue_driver = np.asarray(drivers["revenue"], dtype=float)
        price = np.zeros_like(unit_cost + revenue_driver)
        demand = revenue_driver
        if base.revenue > 0:
            elasticity = inputs["demand_elasticity"]
            if elasticity > 0:
                flags.append(INVALID_ELASTICITY_FLAG)
                elasticity = -1.0
            share = base.variable_cost / base.revenue
            price = pricing.price_change(unit_cost, inputs["pass_through"], share)
            demand = compound(revenue_driver, pricing.demand_change(price, elasticity))
        trajectory = run_operating(
            base,
            OperatingShocks(
                price=price,
                demand=demand,
                unit_cost=unit_cost,
                dso=drivers["working_capital"],
                capex=drivers["capex"],
                rate=drivers["interest"],
            ),
            calendar,
            flags=flags,
        )
        ltm_ebitda = metrics.trailing_sum(trajectory.ebitda, flags=flags)
        ltm_interest = metrics.trailing_sum(trajectory.interest, flags=flags)
        icr = metrics.raw_icr(ltm_ebitda, ltm_interest, flags=flags)
        leverage = metrics.raw_leverage(trajectory.net_debt, ltm_ebitda, flags=flags)
        series = {
            "revenue": trajectory.revenue,
            "variable_cost": trajectory.variable_cost,
            "opex": trajectory.opex,
            "ebitda": trajectory.ebitda,
            "accounts_receivable": trajectory.accounts_receivable,
            "inventory": trajectory.inventory,
            "accounts_payable": trajectory.accounts_payable,
            "net_working_capital": trajectory.net_working_capital,
            "cfads": trajectory.cfads,
            "interest": trajectory.interest,
            "debt": trajectory.debt,
            "cash": trajectory.cash,
            "net_debt": trajectory.net_debt,
            "funding_gap": trajectory.funding_gap,
            "cash_headroom": trajectory.cash_headroom,
            "icr": icr.masked(),
            "nd_ebitda": leverage.masked(),
        }
        return Evaluation(
            series=series,
            metrics={
                "icr": icr.masked(),
                "nd_ebitda": leverage.masked(),
                "cash_headroom": trajectory.cash_headroom,
                "funding_gap": trajectory.funding_gap,
            },
            features=corporate_features(icr.value, icr.defined, leverage.value, leverage.defined),
            flags=flags,
        )

    @staticmethod
    def base(inputs: Inputs, flags: list[str]) -> OperatingBase:
        """The monthly base trajectory from the annual reported figures (spec 5)."""
        flags.append(ANNUAL_FINANCIALS_FLAG)

        def monthly(name):
            return inputs[name] / MONTHS

        rate = inputs["borrowing_rate"]
        gross_debt = inputs.get("gross_debt")
        if gross_debt is None:
            gross_debt = inputs["net_debt"] + inputs["cash"]
        tranches = [
            DebtTranche(
                tranche_id="term",
                opening_balance=gross_debt,
                base_rate=rate,
                margin=inputs["margin"],
                rate_floor=inputs.get("rate_floor"),
                rate_cap=inputs.get("rate_cap"),
                mandatory_repay=monthly("scheduled_amortisation"),
            )
        ]
        limit = inputs.get("credit_limit")
        if limit is not None:
            tranches.append(
                DebtTranche(
                    tranche_id="rcf",
                    opening_balance=inputs["revolver_drawn"],
                    base_rate=rate,
                    margin=inputs["revolver_margin"],
                    revolving=True,
                    limit=limit,
                )
            )
        variable_share = inputs["opex_variable_share"]
        opex = inputs["opex"]
        return OperatingBase(
            revenue=monthly("revenue"),
            variable_cost=monthly("cogs"),
            fixed_cost=monthly("fixed_production_cost"),
            opex_fixed=opex * (1.0 - variable_share) / MONTHS,
            opex_variable=opex * variable_share / MONTHS,
            other_operating_income=monthly("other_operating_income"),
            dso=inputs["dso"],
            dio=inputs["dio"],
            dpo=inputs["dpo"],
            other_current_assets=inputs["other_current_assets"],
            other_current_liabilities=inputs["other_current_liabilities"],
            maintenance_capex=monthly("capex"),
            growth_capex=monthly("growth_capex"),
            tax_rate=inputs["tax_rate"],
            opening_cash=inputs["cash"],
            cash_floor=inputs["cash_floor"],
            restricted_cash=inputs["restricted_cash"],
            dividend=monthly("dividend"),
            tranches=tranches,
        )


class CorporateLoan(OperatingCompany):
    types = {"corp_loan": "Корпоративный кредит"}
    model_id = "credit.corporate.v3"
