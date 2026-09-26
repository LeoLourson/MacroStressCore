"""``equity.factor_stress.v1``: an ordinary share under a factor stress on the horizon.

The price at the horizon is ``P_T = P_0 · exp(β_m f_m + β_s f_s + ε)``: ``f_m`` and ``f_s``
are the log changes of the share's market and sector factors in the approved scenario,
``ε`` its residual return, drawn by the platform for the share alone. A position in another
currency is valued at the snapshot's spot rate and moved by the ``market.fx`` factor of its
pair: ``FX_T = FX_0 · exp(f_fx)``. Dividends are a declared amount per share over the
horizon, translated at the horizon's rate — a convention the result states.

The base scenario has zero shocks. The result tells the P&L against today's value apart
from the change against the base: ``pnl = V_T + D_T − V_0``; ``pnl_vs_base = pnl − D_0``.
There is no monthly path: the model reports the horizon only.

Nothing is silently zero: a missing price, rate, sensitivity or dividend declaration stops
the position; a residual or a dividend of zero must be stated as such in the snapshot.
"""

from math import exp, sqrt

import numpy as np

from msa.contracts.result import AggregationContribution, Diagnostic
from msa.contracts.risk import ApplicabilityLimits
from msa.contracts.units import money, unit_price
from msa.plugin_sdk import (
    CalculationModel,
    DataRequirement,
    DataRequirements,
    Diagnostics,
    FactorRequirement,
    IdiosyncraticFactor,
)
from msa.plugin_sdk.calc import data_quality_level
from msa.plugin_sdk.calc import shapley_exact as shapley
from msa.plugin_sdk.results import distribution, envelope, scalar
from msa.plugins.market import fx
from msa.plugins.market.kinds import PRICE

from .schemas import DIVIDEND, SENSITIVITY, ShareDetails, SharePosition, ShareTerms

PLUGIN_ID = "equity"
PLUGIN_VERSION = "1.0.0"
MODEL_ID = "equity.factor_stress.v1"
SLICE = "market.pnl"
MARKET, SECTOR = "equity.market", "equity.sector"
SENSITIVITY_VALUES = ("beta_market", "beta_sector", "residual_volatility")
DIVIDENDS_AT_HORIZON_FX = "dividends_at_horizon_fx"
RESIDUAL_DECLARED_ZERO = "residual_declared_zero"
STALE_PRICE_DAYS = 10

METRICS = (
    "equity.value_current",
    "equity.value_horizon",
    "equity.pnl",
    "equity.pnl_vs_base",
    "equity.loss",
    "equity.dividends",
    "equity.log_return",
)


class ShareFactorStress(CalculationModel):
    model_id = MODEL_ID
    version = "1.0.0"
    label = "Факторный стресс акции на горизонте"
    instrument_types = ("common_stock",)
    metrics = METRICS
    required_metrics = ("equity.value_current", "equity.pnl", "equity.loss")
    slices = (SLICE,)
    factors = (MARKET, SECTOR, fx.FX_FACTOR)
    details_schema = ShareDetails
    description = (
        "Цена на горизонте P_T = P_0·exp(β_m·f_m + β_s·f_s + ε); валютный фактор отдельно "
        "переводит стоимость в базовую валюту; дивиденды — заданная сумма на горизонт."
    )
    limits = ApplicabilityLimits(
        approved_uses=["scenario_analysis", "early_warning", "manual_review_ranking"],
        prohibited_uses=["market_fair_value", "trading_decisions", "regulatory_market_risk"],
        note="Экспертные чувствительности без автоматической калибровки; только длинные позиции.",
    )

    # Requirements ----------------------------------------------------------------------

    def requirements(self, position, options):
        instrument = position.instrument
        terms = ShareTerms.model_validate(instrument.terms)
        data = [
            DataRequirement(
                key="price",
                kind=PRICE,
                subject=instrument.instrument_id,
                purpose="цена акции на дату оценки",
            ),
            DataRequirement(
                key="sensitivity",
                kind=SENSITIVITY,
                subject=instrument.instrument_id,
                purpose="чувствительности акции к факторам",
            ),
            DataRequirement(
                key="dividend",
                kind=DIVIDEND,
                subject=instrument.instrument_id,
                purpose="дивиденды на горизонт",
            ),
        ]
        factors = [
            FactorRequirement(factor_id=MARKET, key=terms.market_index),
            FactorRequirement(factor_id=SECTOR, key=terms.sector),
        ]
        rate = fx.requirement(instrument.currency, options.base_currency)
        if rate is not None:
            data.append(rate)
            factors.append(fx.factor(instrument.currency, options.base_currency))
        return DataRequirements(data=data, factors=factors)

    # Validation ------------------------------------------------------------------------

    def validate(self, prepared) -> Diagnostics:
        context = prepared.context
        instrument = context.instrument
        items: list[Diagnostic] = []

        def error(code, message, path=""):
            items.append(Diagnostic(code=code, severity="error", message=message, path=path))

        terms = ShareTerms.model_validate(instrument.terms)
        position = SharePosition.model_validate(context.position.params)
        price = prepared.item("price")
        sensitivity = prepared.item("sensitivity")
        dividend = prepared.item("dividend")
        rate = fx.spot(prepared, instrument.currency, context.base_currency)
        if rate is None:
            pair = fx.pair(instrument.currency, context.base_currency)
            reason = prepared.missing.get(fx.FX_KEY, "missing")
            error(f"fx_missing:{pair}", f"нет курса {pair} на дату оценки ({reason})", "/data/fx")
        elif rate <= 0:
            error("fx_invalid", "курс должен быть положительным", "/data/fx")
        value = None
        if price is not None:
            quote = price.values.get("price")
            if quote is None or quote.value <= 0:
                error("price_invalid", "цена должна быть положительным числом", "/data/price")
            elif quote.unit != unit_price(instrument.currency):
                error(
                    "price_currency_mismatch",
                    f"цена в {quote.unit}, акция торгуется в {instrument.currency}",
                    "/data/price",
                )
            elif rate is not None and rate > 0:
                value = position.quantity.value * quote.value * rate / 1e6
            age = (prepared.as_of - price.observed_on).days
            if age > STALE_PRICE_DAYS:
                items.append(
                    Diagnostic(
                        code="price_stale",
                        severity="warning",
                        message=f"цена старше {STALE_PRICE_DAYS} дней",
                        path="/data/price",
                    )
                )
        if sensitivity is not None:
            for name in SENSITIVITY_VALUES:
                if name not in sensitivity.values:
                    # A residual of zero is an explicit statement, never an absent value.
                    error(
                        f"sensitivity_missing:{name}",
                        f"не задано значение {name}",
                        "/data/sensitivity",
                    )
            for parameter in sensitivity.values.values():
                for evidence in parameter.evidence:
                    if evidence.kind == "expert_assumption" and not evidence.author:
                        error("sensitivity_without_author", "у экспертной оценки нет автора")
            index = sensitivity.attributes.get("market_index")
            sector = sensitivity.attributes.get("sector")
            if index != terms.market_index or sector != terms.sector:
                error(
                    "calibration_mismatch",
                    f"чувствительности оценены к {index}/{sector}, акция относится к "
                    f"{terms.market_index}/{terms.sector}",
                    "/data/sensitivity",
                )
        if dividend is not None:
            amount = dividend.values.get("amount")
            if amount is None:
                error(
                    "dividends_not_declared",
                    "не задана сумма дивидендов на горизонт",
                    "/data/dividend",
                )
            elif amount.unit != unit_price(instrument.currency) or amount.value < 0:
                error(
                    "dividend_invalid",
                    "дивиденды — неотрицательная сумма в валюте акции",
                    "/data/dividend",
                )
            horizon = dividend.attributes.get("horizon_months")
            if horizon != prepared.horizon:
                error(
                    "dividend_horizon_mismatch",
                    f"дивиденды заданы на {horizon} мес., горизонт расчёта {prepared.horizon}",
                    "/data/dividend",
                )
        shocks = []
        residual = None
        if sensitivity is not None and "residual_volatility" in sensitivity.values:
            residual = sensitivity.values["residual_volatility"].value
            sigma = residual * sqrt(prepared.horizon / 12)
            if sigma > 0:
                shocks.append(
                    IdiosyncraticFactor(
                        name=f"equity.residual:{instrument.instrument_id}",
                        subject=instrument.instrument_id,
                        sigma=sigma,
                    )
                )
        return Diagnostics(
            items=items,
            exposures={SLICE: value},
            idiosyncratic=shocks,
            data_quality=self.quality(prepared, price, sensitivity),
            blocked_status="needs_review"
            if any(i.code.startswith("fx_missing") for i in items)
            else "invalid",
        )

    @staticmethod
    def quality(prepared, price, sensitivity):
        """Fresh prices and historical sensitivities score high; expert ones cap the score."""
        if price is None or sensitivity is None:
            return data_quality_level(None)
        freshness = exp(-max(0, (prepared.as_of - price.observed_on).days) / 30)
        kinds = {e.kind for p in sensitivity.values.values() for e in p.evidence}
        source = 1.0 if kinds == {"historical_estimate"} else 0.6
        return data_quality_level(0.5 * freshness + 0.5 * source)

    # Calculation -----------------------------------------------------------------------

    def calculate(self, prepared, context):
        instrument = prepared.context.instrument
        base = context.base_currency
        terms = ShareTerms.model_validate(instrument.terms)
        quantity = SharePosition.model_validate(prepared.context.position.params).quantity.value
        price0 = prepared.item("price").values["price"].value
        sensitivity = prepared.item("sensitivity").values
        beta_m = sensitivity["beta_market"].value
        beta_s = sensitivity["beta_sector"].value
        residual = sensitivity["residual_volatility"].value
        dividend = prepared.item("dividend").values["amount"].value
        rate0 = fx.spot(prepared, instrument.currency, base)
        scenario = context.scenario
        flags: list[str] = [DIVIDENDS_AT_HORIZON_FX] if dividend > 0 else []
        shape = (scenario.replicates, scenario.points)

        def factor(factor_id, key):
            names = scenario.parameters_for(factor_id, key)
            if not names:
                flags.append(f"factor_not_in_scenario:{factor_id}:{key}")
                return 0.0, np.zeros(shape)
            central = sum(scenario.central(name) for name in names)
            return float(central), np.sum([scenario.draws(name) for name in names], axis=0)

        market_c, market = factor(MARKET, terms.market_index)
        sector_c, sector = factor(SECTOR, terms.sector)
        fx_c, fx_draws = fx.log_change(scenario, instrument.currency, base, flags)
        if residual > 0:
            noise = scenario.idiosyncratic(f"equity.residual:{instrument.instrument_id}")
        else:
            flags.append(RESIDUAL_DECLARED_ZERO)
            noise = np.zeros(shape)

        def outcome(log_return, fx_log):
            price = price0 * np.exp(log_return)
            rate = rate0 * np.exp(fx_log)
            value = quantity * price * rate / 1e6
            income = quantity * dividend * rate / 1e6
            return price, rate, value, income

        value0 = quantity * price0 * rate0 / 1e6
        dividends_base = quantity * dividend * rate0 / 1e6
        log_return = beta_m * market + beta_s * sector + noise
        _, _, value_t, income_t = outcome(log_return, fx_draws)
        pnl = value_t + income_t - value0
        central_log = beta_m * market_c + beta_s * sector_c
        price_c, rate_c, value_c, income_c = outcome(central_log, fx_c)
        pnl_c = float(value_c + income_c - value0)

        def central_pnl(active):
            m = market_c if MARKET in active else 0.0
            s = sector_c if SECTOR in active else 0.0
            f = fx_c if fx.FX_FACTOR in active else 0.0
            _, _, v, d = outcome(beta_m * m + beta_s * s, f)
            return float(v + d - value0)

        players = [MARKET, SECTOR] + ([fx.FX_FACTOR] if instrument.currency != base else [])
        shares = shapley(players, central_pnl)
        keys = {
            MARKET: terms.market_index,
            SECTOR: terms.sector,
            fx.FX_FACTOR: fx.pair(instrument.currency, base),
        }
        labels = {MARKET: "Рынок", SECTOR: "Отрасль", fx.FX_FACTOR: "Валютный курс"}
        losses = -pnl.reshape(-1)
        counts, edges = np.histogram(losses, bins=20)
        unit = money(base)
        metrics = {
            "equity.value_current": scalar("equity.value_current", unit, value0),
            "equity.value_horizon": distribution(
                "equity.value_horizon", unit, value_t, value=float(value_c)
            ),
            "equity.pnl": distribution("equity.pnl", unit, pnl, value=pnl_c),
            "equity.pnl_vs_base": distribution(
                "equity.pnl_vs_base", unit, pnl - dividends_base, value=pnl_c - dividends_base
            ),
            "equity.loss": distribution("equity.loss", unit, losses, value=-pnl_c, tail=True),
            "equity.dividends": scalar("equity.dividends", unit, float(income_c)),
            "equity.log_return": distribution(
                "equity.log_return", "log_return", log_return, value=float(central_log)
            ),
        }
        details = ShareDetails(
            currency=instrument.currency,
            base_currency=base,
            price=price0,
            price_date=prepared.item("price").observed_on.isoformat(),
            fx=rate0,
            quantity=quantity,
            beta_market=beta_m,
            beta_sector=beta_s,
            residual_sigma=residual * sqrt(context.horizon / 12),
            dividend_per_share=dividend,
            value_current=value0,
            central={
                "log_return": float(central_log),
                "price": float(price_c),
                "fx": float(rate_c),
                "value": float(value_c),
                "dividends": float(income_c),
                "pnl": pnl_c,
                "pnl_vs_base": pnl_c - dividends_base,
            },
            factor_contributions=[
                {"factor_id": f, "key": keys[f], "label": labels[f], "contribution": shares[f]}
                for f in players
            ],
            loss_histogram={"edges": edges.tolist(), "counts": counts.tolist()},
            conventions=[
                "Цена на горизонте: P_T = P_0·exp(β_m·f_m + β_s·f_s + ε).",
                "Дивиденды заданы суммой на горизонт и пересчитаны по курсу конца горизонта.",
                "P&L — к текущей стоимости; изменение к базе — за вычетом дивидендов базы.",
            ],
        )
        sources = []
        for item in (
            prepared.item("price"),
            prepared.item("sensitivity"),
            prepared.item("dividend"),
            prepared.item(fx.FX_KEY),
        ):
            if item is None:
                continue
            for parameter in item.values.values():
                for evidence in parameter.evidence:
                    if evidence not in sources:
                        sources.append(evidence)
        quantity_evidence = SharePosition.model_validate(prepared.context.position.params).quantity
        for evidence in quantity_evidence.evidence:
            if evidence not in sources:
                sources.append(evidence)
        return envelope(
            prepared,
            context,
            self,
            plugin_id=PLUGIN_ID,
            plugin_version=PLUGIN_VERSION,
            status="ok",
            data_quality=self.quality(
                prepared, prepared.item("price"), prepared.item("sensitivity")
            ),
            metrics=metrics,
            details=details.model_dump(mode="json"),
            details_schema="equity.share_details/1",
            input_sources={
                name: sorted({e.source_id for p in item.values.values() for e in p.evidence})
                for name, item in (
                    ("price", prepared.item("price")),
                    ("sensitivity", prepared.item("sensitivity")),
                    ("dividend", prepared.item("dividend")),
                    ("fx", prepared.item(fx.FX_KEY)),
                )
                if item is not None
            },
            sources=sources,
            flags=list(dict.fromkeys(flags)),
            limits=self.limits,
            contributions=[
                AggregationContribution(
                    slice_id=SLICE,
                    measure="equity.pnl",
                    unit=unit,
                    horizon=context.horizon,
                    scenario_id=scenario.scenario_id,
                    exposure=value0,
                    exposure_basis="market_value",
                    draws=losses.tolist(),
                )
            ],
            model_versions={"equity.factor_stress": self.version},
        )
