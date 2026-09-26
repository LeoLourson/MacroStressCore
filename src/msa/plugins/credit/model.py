"""The credit model as the platform's calculation models: one per family.

``requirements`` asks for the borrower's statement, peers and the family's market quotes;
``validate`` assembles the credit profile and judges whether it can be calculated;
``calculate`` runs the position's risk on the run's joint realisations and wraps its
``RiskResult`` in the common envelope, with typed metrics and the position's
contribution to the credit-loss slice.
"""

from pydantic import ValidationError

from msa.contracts.result import AggregationContribution, Diagnostic, MetricValue
from msa.plugin_sdk import CalculationModel, Diagnostics
from msa.plugin_sdk.calc import data_quality_level
from msa.plugin_sdk.results import envelope, scalar

from . import calibration, profile
from .contracts import RiskResult
from .factors import FACTORS
from .families import family_for
from .position_risk import MODEL_VERSION, AssetRiskInput, review_flags, run_asset

PLUGIN_ID = "credit"
PLUGIN_VERSION = "3.2.0"
SLICE = "credit.loss"
REGISTRY_OPTION = "credit.registry_id"
RUB = "RUB_million"

#: Quantile name in ``RiskResult`` -> platform metric id.
QUANTILE_METRICS = {
    "delta_expected_loss": "credit.delta_expected_loss",
    "pd": "credit.pd_horizon",
    "risk_score": "credit.risk_score_horizon",
    "delta_pd": "credit.delta_pd",
    "delta_risk_score": "credit.delta_risk_score",
    "icr": "credit.icr",
    "funding_gap": "credit.funding_gap",
    "escrow_coverage": "credit.escrow_coverage",
    "debt_equity": "credit.debt_equity",
    "position_price_change": "credit.position_price_change",
}
VALUE_METRICS = (
    "credit.expected_loss",
    "credit.pd",
    "credit.risk_score",
    "credit.ead",
    "credit.lgd",
)
METRICS = (*QUANTILE_METRICS.values(), *VALUE_METRICS)


class CreditModel(CalculationModel):
    version = MODEL_VERSION
    metrics = METRICS
    required_metrics = ("credit.ead",)
    slices = (SLICE,)
    factors = tuple(spec.factor_id for spec in FACTORS)
    details_schema = RiskResult

    def __init__(self, family):
        self.family = family
        self.model_id = family.model_id
        self.instrument_types = tuple(family.types)
        self.label = "Кредитный риск: " + ", ".join(family.types.values()).lower()
        self.description = (
            "Помесячная модель заёмщика на совместных сценариях: PD, ожидаемые потери, "
            "ковенанты, ликвидность, вклад каналов и обратный стресс-тест."
        )
        self.review_flags = review_flags()

    def requirements(self, position, options):
        return profile.requirements(position)

    def validate(self, prepared) -> Diagnostics:
        context = prepared.context
        items: list[Diagnostic] = []
        params = context.position.params
        ead = (params.get("ead") or {}).get("value") if isinstance(params, dict) else None
        exposures = {SLICE: float(ead) if ead is not None else None}

        def blocked(code, message, status="invalid"):
            return Diagnostics(
                items=[*items, Diagnostic(code=code, severity="error", message=message)],
                exposures=exposures,
                blocked_status=status,
            )

        if context.instrument.currency != "RUB" or context.base_currency != "RUB":
            return blocked(
                "credit_currency_unsupported",
                "кредитные модели считают позиции и портфели только в рублях",
            )
        if context.issuer is None or not context.issuer.okved:
            return blocked("issuer_okved_missing", "у заёмщика не указан ОКВЭД")
        for key, reason in sorted(prepared.missing.items()):
            if reason == "dated_after_as_of":
                items.append(
                    Diagnostic(
                        code=f"data_dated_after_as_of:{key}",
                        severity="warning",
                        message="данные есть только после даты оценки и не используются",
                    )
                )
        try:
            built = profile.build(prepared)
        except (ValidationError, ValueError) as exc:
            return blocked("profile_invalid", str(exc))
        quality = data_quality_level(built.dq)
        if built.status == "needs_review":
            # Missing inputs are not replaced with invented numbers.
            result = blocked(
                "profile_needs_review:" + ",".join(built.flags),
                "профиль позиции требует проверки",
                status="needs_review",
            )
            return result.model_copy(update={"data_quality": quality})
        problems = self.family.problems(built.financials)
        if problems:
            name, message = problems[0]
            result = blocked(f"V2:/financials/{name}", message)
            return result.model_copy(update={"data_quality": quality})
        return Diagnostics(items=items, exposures=exposures, data_quality=quality)

    def calculate(self, prepared, context):
        built = profile.build(prepared)
        registry_id = str(prepared.options.get(REGISTRY_OPTION) or calibration.NONE)
        registry = calibration.load(registry_id)
        risk = run_asset(
            AssetRiskInput(built, context.scenario.graph, context.as_of, context.horizon),
            context.scenario_set,
            registry.model,
            context.seed,
        )
        return self.wrap(prepared, context, risk, built, registry)

    def wrap(self, prepared, context, risk: RiskResult, built, registry):
        family = family_for(built.asset_type)
        metrics = {}
        for name, item in risk.quantiles.items():
            metric_id = QUANTILE_METRICS.get(name)
            if metric_id is not None:
                metrics[metric_id] = MetricValue(
                    metric_id=metric_id,
                    unit=item.unit,
                    quantiles=item.model_copy(update={"name": metric_id}),
                )
        credit = risk.credit
        if credit is not None:
            if credit.expected_loss is not None:
                metrics["credit.expected_loss"] = scalar(
                    "credit.expected_loss", RUB, credit.expected_loss
                )
            if credit.pd is not None:
                metrics["credit.pd"] = scalar("credit.pd", "fraction", credit.pd)
            if credit.risk_score is not None:
                metrics["credit.risk_score"] = scalar(
                    "credit.risk_score", "fraction", credit.risk_score
                )
            if credit.lgd is not None:
                metrics["credit.lgd"] = scalar("credit.lgd", "fraction", credit.lgd)
        metrics["credit.ead"] = scalar("credit.ead", RUB, built.ead)

        contributions = []
        if risk.aggregation_draws is not None:
            rule = registry.inclusion
            if risk.status == "ok":
                admission = "included"
            elif rule is not None and rule.admits(risk):
                admission = f"admitted:{rule.rule_id}"
            else:
                admission = f"excluded:{risk.status}"
            contributions.append(
                AggregationContribution(
                    slice_id=SLICE,
                    measure="credit.delta_expected_loss",
                    unit=RUB,
                    horizon=risk.horizon,
                    scenario_id=context.scenario.scenario_id,
                    exposure=built.ead,
                    exposure_basis="ead",
                    admission=admission,
                    draws=list(risk.aggregation_draws),
                )
            )
        assumptions = sorted(
            {item.assumption for item in family.fields if item.assumption} & set(risk.flags)
        )
        sources = []
        for evidence in (
            *(e for items in built.field_evidence.values() for e in items),
            *(e for parameter in built.financials.values() for e in parameter.evidence),
            *(e for covenant in built.covenants for e in covenant.evidence),
            *(e for collateral in built.collateral for e in collateral.evidence),
        ):
            if evidence not in sources:
                sources.append(evidence)
        applicability = "applicable" if risk.status == "ok" else "limited"
        if risk.status == "invalid":
            applicability = "not_applicable"
        return envelope(
            prepared,
            context,
            self,
            plugin_id=PLUGIN_ID,
            plugin_version=PLUGIN_VERSION,
            macro_draws_sha256=risk.macro_draws_sha256,
            applicability=applicability,
            data_quality=data_quality_level(built.dq),
            status=risk.status,
            metrics=metrics,
            details=risk.model_dump(mode="json"),
            details_schema="credit.risk_result/1",
            input_sources=risk.input_sources,
            sources=sources,
            assumptions=assumptions,
            flags=list(dict.fromkeys(risk.flags)),
            limits=risk.limits,
            contributions=contributions,
            model_versions=risk.model_versions | {"registry": registry.registry_id},
        )
