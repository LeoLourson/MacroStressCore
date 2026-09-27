"""Project finance with escrow accounts (spec 11): a developer's construction loan.

Buyers' money sits on escrow until the object is commissioned; the construction debt is
repaid from its release. Coverage is the escrow balance over the debt it is to repay.
"""

import numpy as np

from ..family import CovenantMetric, CreditFamily, Evaluation, Inputs, Series
from ..family import InputField as F
from ..math import project_finance
from ..math.credit import coverage_feature

SUBSIDY_SIMPLIFIED_FLAG = "project_rate_subsidy_simplified"

M = "RUB_million"


class ProjectFinance(CreditFamily):
    types = {"pf_escrow": "Проектное финансирование с эскроу"}
    model_id = "credit.project_finance.v3"
    segment = "project_finance"
    fields = (
        F("credit_limit", M, "Лимит проектного кредита", required=True, source="terms"),
        F(
            "equity",
            M,
            "Собственные средства застройщика",
            required=True,
            hint="Деньги застройщика, ещё не вложенные в стройку",
        ),
        F("capex_month_1_12", M, "Затраты на строительство в месяц, 1–12 мес.", required=True),
        F("monthly_sales", M, "Продажи в месяц", required=True),
        F("base_rate", "fraction", "Базовая ставка", required=True, source="terms"),
        F("capex_month_13_24", M, "Затраты на строительство в месяц, 13–24 мес.", default=0.0),
        F("sales_start_month", "months", "Месяц начала продаж", default=1.0),
        F(
            "commissioning_month",
            "months",
            "Месяц ввода объекта",
            hint="Месяц сдачи объекта; эскроу раскрывается в следующем. "
            "Если пусто — не раскрывается",
        ),
        F(
            "debt",
            M,
            "Долг проекта на начало",
            default=0.0,
            hint="Проектный кредит, уже выбранный на начало расчёта",
        ),
        F(
            "escrow",
            M,
            "Остаток на счетах эскроу на начало",
            default=0.0,
            hint="Деньги дольщиков на эскроу на начало расчёта",
        ),
        F(
            "subsidized_rate",
            "fraction",
            "Субсидированная ставка",
            hint="Пониженная ставка проектного кредита с господдержкой. "
            "Если пусто — платится базовая ставка",
            source="terms",
        ),
    )
    disclosure = (
        "credit_limit",
        "equity",
        "capex_month_1_12",
        "capex_month_13_24",
        "monthly_sales",
        "base_rate",
        "subsidized_rate",
        "commissioning_month",
    )
    series = (
        Series("sales_receipts", "Поступления от продаж"),
        Series("restricted_escrow", "Средства на эскроу", kind="stock_money"),
        Series("debt", "Долг", kind="stock_money"),
        Series("interest", "Проценты"),
        Series("cash", "Денежные средства проекта", kind="stock_money"),
        Series("escrow_coverage", "Покрытие долга эскроу", unit="ratio", kind="ratio"),
        Series("funding_gap", "Дефицит финансирования", kind="stock_money"),
        Series("cash_headroom", "Запас ликвидности", kind="stock_money"),
    )
    covenant_metrics = (CovenantMetric("escrow_coverage", "Покрытие долга эскроу", "ge", 1.0),)
    decision_metrics = ("escrow_coverage", "funding_gap")
    review_flags = frozenset({SUBSIDY_SIMPLIFIED_FLAG})

    def evaluate(self, inputs: Inputs, calendar, drivers) -> Evaluation:
        flags: list[str] = []
        months = np.arange(1, calendar.horizon + 1)
        capex = np.where(months <= 12, inputs["capex_month_1_12"], inputs["capex_month_13_24"])
        sales = np.where(months >= inputs["sales_start_month"], inputs["monthly_sales"], 0.0)
        rate = inputs.get("subsidized_rate")
        if rate is None:
            rate = inputs["base_rate"]
        else:
            flags.append(SUBSIDY_SIMPLIFIED_FLAG)
        commissioning = inputs.get("commissioning_month")
        equity = inputs["equity"]
        trajectory = project_finance.run(
            project_finance.ProjectBase(
                capex=capex,
                units_sold=sales,
                unit_price=1.0,
                opening_equity_cash=equity,
                # The developer's own funds go into construction before the loan is drawn.
                required_equity=equity,
                opening_escrow=inputs["escrow"],
                opening_debt=inputs["debt"],
                project_rate=rate,
                credit_limit=inputs["credit_limit"],
                # Escrow is released the month after the object is commissioned.
                release_from_month=None if commissioning is None else int(commissioning) + 1,
            ),
            calendar,
            shocks={
                "price": 0.0,
                "volume": drivers["revenue"],
                "capex": drivers["capex"],
                "rate": drivers["interest"],
            },
            flags=flags,
        )
        coverage = trajectory.coverage
        series = {
            "sales_receipts": trajectory.sales_receipts,
            "restricted_escrow": trajectory.restricted_escrow,
            "debt": trajectory.construction_debt,
            "interest": trajectory.interest,
            "cash": trajectory.operating_cash,
            "escrow_coverage": coverage,
            "funding_gap": trajectory.funding_gap,
            "cash_headroom": -trajectory.funding_gap,
        }
        return Evaluation(
            series=series,
            metrics={
                "escrow_coverage": coverage,
                "cash_headroom": -trajectory.funding_gap,
                "funding_gap": trajectory.funding_gap,
                "limit_excess": np.broadcast_to(
                    trajectory.limit_excess[..., None], trajectory.funding_gap.shape
                ),
            },
            features={"r_icr": coverage_feature(coverage, np.isfinite(coverage))},
            flags=flags,
        )
