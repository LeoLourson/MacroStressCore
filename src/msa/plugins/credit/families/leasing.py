"""Leasing companies (spec 12): the lessor's book, its funding and its capital.

The lessor's credit is read from interest coverage and debt to equity. The lessees' own
credit losses are not modelled yet, which is flagged on every result.
"""

from msa.engine import metrics
from msa.engine.credit import corporate_features

from ..family import CovenantMetric, CreditFamily, Evaluation, Inputs, Series, compound
from ..family import InputField as F
from ..math import leasing

ECL_MISSING_FLAG = "leasing_ecl_missing"

M = "RUB_million"
MONTHS = 12


class LeasingCompany(CreditFamily):
    types = {"leasing": "Кредит лизинговой компании"}
    model_id = "credit.leasing.v3"
    segment = "leasing"
    fields = (
        F("net_investment_leases", M, "Чистые инвестиции в лизинг", required=True),
        F("new_business", M, "Новый бизнес за год", required=True),
        F("debt", M, "Долг", required=True),
        F("equity", M, "Капитал", required=True),
        F("portfolio_yield", "fraction", "Доходность лизингового портфеля", required=True),
        F("amortization_rate", "fraction", "Годовая амортизация портфеля", required=True),
        F("borrowing_rate", "fraction", "Ставка фондирования", required=True),
        F("opex", M, "Операционные расходы за год", default=0.0),
        F("prepayment_share", "fraction", "Досрочные погашения за год", default=0.0),
        F("advance_rate", "fraction", "Доля аванса", default=0.0),
        F(
            "tax_rate",
            "fraction",
            "Ставка налога на прибыль",
            default=0.20,
            assumption="assumed_tax_rate",
            hint="без неё — 20 % по допущению",
        ),
    )
    disclosure = (
        "net_investment_leases",
        "new_business",
        "debt",
        "equity",
        "portfolio_yield",
        "amortization_rate",
        "borrowing_rate",
        "opex",
        "advance_rate",
    )
    series = (
        Series("net_investment", "Чистые инвестиции в лизинг", kind="stock_money"),
        Series("finance_income", "Процентный доход"),
        Series("funding_cost", "Стоимость фондирования"),
        Series("ppop", "Прибыль до резервов"),
        Series("net_income", "Чистая прибыль"),
        Series("equity", "Капитал", kind="stock_money"),
        Series("debt", "Долг", kind="stock_money"),
        Series("icr", "Покрытие процентов (ICR)", unit="ratio", kind="ratio"),
        Series("debt_equity", "Долг / капитал", unit="ratio", kind="ratio"),
    )
    covenant_metrics = (
        CovenantMetric("icr", "ICR (покрытие процентов)", "ge", 1.5),
        CovenantMetric("debt_equity", "Долг / капитал", "le", 6.0),
    )
    decision_metrics = ("icr", "debt_equity")
    review_flags = frozenset({ECL_MISSING_FLAG})

    def evaluate(self, inputs: Inputs, calendar, drivers) -> Evaluation:
        flags = [ECL_MISSING_FLAG]
        book = inputs["net_investment_leases"]
        trajectory = leasing.run(
            leasing.LeasingBase(
                opening_nil=book,
                scheduled_principal=inputs["amortization_rate"] * book / MONTHS,
                prepayment=inputs["prepayment_share"] * book / MONTHS,
                new_business=inputs["new_business"] / MONTHS,
                advance_rate=inputs["advance_rate"],
                portfolio_yield=inputs["portfolio_yield"],
                opex=inputs["opex"] / MONTHS,
                opening_debt=inputs["debt"],
                funding_rate=inputs["borrowing_rate"],
                opening_equity=inputs["equity"],
                tax_rate=inputs["tax_rate"],
            ),
            calendar,
            shocks={
                "new_business": drivers["revenue"],
                "funding_rate": drivers["interest"],
                "opex": compound(drivers["cogs"], drivers["logistics"]),
            },
            flags=flags,
        )
        ltm_ppop = metrics.trailing_sum(trajectory.ppop, flags=flags)
        ltm_funding = metrics.trailing_sum(trajectory.funding_cost, flags=flags)
        # ICR covers interest with earnings before it (spec 5.5); PPOP is already after funding.
        icr = metrics.raw_icr(ltm_ppop + ltm_funding, ltm_funding, flags=flags)
        debt_equity = metrics.raw_debt_to_equity(trajectory.debt, trajectory.equity, flags=flags)
        return Evaluation(
            series={
                "net_investment": trajectory.net_investment,
                "finance_income": trajectory.finance_income,
                "funding_cost": trajectory.funding_cost,
                "ppop": trajectory.ppop,
                "net_income": trajectory.net_income,
                "equity": trajectory.equity,
                "debt": trajectory.debt,
                "icr": icr.masked(),
                "debt_equity": debt_equity.masked(),
            },
            metrics={"icr": icr.masked(), "debt_equity": debt_equity.masked()},
            features=corporate_features(
                icr.value, icr.defined, debt_equity.value, debt_equity.defined
            ),
            flags=flags,
        )
