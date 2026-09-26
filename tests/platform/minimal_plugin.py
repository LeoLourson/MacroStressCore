"""A minimal, self-contained plugin used only by the platform tests.

``minimal_cash`` holds an amount in its own currency; ``minimal.cash.v1`` converts it to the
run's base currency at the snapshot's spot rate, reports it as ``minimal.value`` (a point
value) and its change over the horizon as ``minimal.pnl`` (a distribution driven by the FX
factor and a position-specific idiosyncratic shock), and contributes its loss (negative P&L)
to the shared ``market.pnl`` slice the real ``market`` plugin declares.

Several broken subclasses of the model are provided for exercising the dispatcher's output
checks (``msa.engine.dispatch.output_problems``): each breaks exactly one declared contract.
"""

from pydantic import BaseModel

from msa.contracts.common import Contract
from msa.contracts.evidence import Parameter
from msa.contracts.result import AggregationContribution, MetricValue
from msa.contracts.units import money
from msa.plugin_sdk import (
    BASE_MONEY,
    CalculationModel,
    DataRequirements,
    Diagnostics,
    IdiosyncraticFactor,
    InstrumentTypeSpec,
    MetricSpec,
    Plugin,
)
from msa.plugin_sdk.results import distribution, envelope, scalar
from msa.plugins.market import fx
from msa.plugins.market import plugin as market_plugin

#: The real market plugin, needed alongside ``plugin`` because this model reads its
#: ``market.fx`` factor and contributes to its ``market.pnl`` slice.
MARKET_PLUGIN = market_plugin

PLUGIN_ID = "minimal"
PLUGIN_VERSION = "1.0.0"
TYPE_ID = "minimal_cash"
MODEL_ID = "minimal.cash.v1"
SLICE_ID = "market.pnl"
VALUE_METRIC = "minimal.value"
PNL_METRIC = "minimal.pnl"


class MinimalTerms(Contract):
    note: str = ""


class MinimalPosition(Contract):
    #: By convention, in ``<instrument currency>_million`` (not enforced by the schema).
    amount: Parameter


def shock_name(instrument_id: str) -> str:
    return f"minimal.noise:{instrument_id}"


class CashModel(CalculationModel):
    """Values a cash amount in the base currency and reports its stressed change."""

    model_id = MODEL_ID
    version = "1.0.0"
    label = "Minimal cash valuation"
    instrument_types = (TYPE_ID,)
    metrics = (VALUE_METRIC, PNL_METRIC)
    required_metrics = (VALUE_METRIC,)
    slices = (SLICE_ID,)
    factors = (fx.FX_FACTOR,)

    def requirements(self, position, options):
        currency = position.instrument.currency
        req = fx.requirement(currency, options.base_currency)
        factor_req = fx.factor(currency, options.base_currency)
        return DataRequirements(
            data=[req] if req else [],
            factors=[factor_req] if factor_req else [],
        )

    def validate(self, prepared) -> Diagnostics:
        params = MinimalPosition.model_validate(prepared.context.position.params)
        instrument_id = prepared.context.instrument.instrument_id
        shock = IdiosyncraticFactor(
            name=shock_name(instrument_id),
            subject=instrument_id,
            sigma=0.01,
        )
        return Diagnostics(exposures={SLICE_ID: params.amount.value}, idiosyncratic=[shock])

    def calculate(self, prepared, context):
        instrument = prepared.context.instrument
        currency, base = instrument.currency, context.base_currency
        params = MinimalPosition.model_validate(prepared.context.position.params)
        rate = fx.spot(prepared, currency, base)
        value_base = params.amount.value * rate

        flags: list[str] = []
        fx_central, fx_draws = fx.log_change(context.scenario, currency, base, flags)
        noise = context.scenario.idiosyncratic(shock_name(instrument.instrument_id))
        pnl_central = value_base * fx_central
        pnl_draws = value_base * (fx_draws + noise)
        loss_draws = (-pnl_draws).reshape(-1)

        unit = money(base)
        metrics = {
            VALUE_METRIC: scalar(VALUE_METRIC, unit, value_base),
            PNL_METRIC: distribution(PNL_METRIC, unit, pnl_draws, value=pnl_central),
        }
        contributions = [
            AggregationContribution(
                slice_id=SLICE_ID,
                measure=SLICE_ID,
                unit=unit,
                horizon=context.horizon,
                scenario_id=context.scenario.scenario_id,
                exposure=value_base,
                exposure_basis="market_value",
                admission="included",
                draws=list(loss_draws),
            )
        ]
        return envelope(
            prepared,
            context,
            self,
            plugin_id=PLUGIN_ID,
            plugin_version=PLUGIN_VERSION,
            status="ok",
            metrics=metrics,
            contributions=contributions,
            flags=flags,
        )


# -- Broken variants, one declared contract broken each --------------------------------


class WrongMetricUnitModel(CashModel):
    """Reports ``minimal.value`` in the wrong unit."""

    model_id = "minimal.wrong_metric_unit.v1"

    def calculate(self, prepared, context):
        result = super().calculate(prepared, context)
        bad = result.metrics[VALUE_METRIC].model_copy(
            update={"unit": "fraction", "quantiles": None}
        )
        return result.model_copy(update={"metrics": {**result.metrics, VALUE_METRIC: bad}})


class UndeclaredMetricModel(CashModel):
    """Reports a metric the model never declared."""

    model_id = "minimal.undeclared_metric.v1"

    def calculate(self, prepared, context):
        result = super().calculate(prepared, context)
        extra = scalar("minimal.not_declared", money(context.base_currency), 1.0)
        return result.model_copy(
            update={"metrics": {**result.metrics, "minimal.not_declared": extra}}
        )


class DistributionWithoutQuantilesModel(CashModel):
    """Reports the distribution metric as a bare value, without quantiles."""

    model_id = "minimal.no_quantiles.v1"

    def calculate(self, prepared, context):
        result = super().calculate(prepared, context)
        bad = MetricValue(metric_id=PNL_METRIC, unit=result.metrics[PNL_METRIC].unit, value=0.0)
        return result.model_copy(update={"metrics": {**result.metrics, PNL_METRIC: bad}})


class MissingRequiredMetricModel(CashModel):
    """Omits the required ``minimal.value`` metric."""

    model_id = "minimal.missing_required.v1"

    def calculate(self, prepared, context):
        result = super().calculate(prepared, context)
        metrics = dict(result.metrics)
        del metrics[VALUE_METRIC]
        return result.model_copy(update={"metrics": metrics})


class UndeclaredSliceModel(CashModel):
    """Contributes to a slice the model never declared."""

    model_id = "minimal.undeclared_slice.v1"

    def calculate(self, prepared, context):
        result = super().calculate(prepared, context)
        bad = result.contributions[0].model_copy(update={"slice_id": "credit.loss"})
        return result.model_copy(update={"contributions": [bad]})


class WrongContributionUnitModel(CashModel):
    """Contributes to its declared slice in the wrong unit."""

    model_id = "minimal.wrong_contribution_unit.v1"

    def calculate(self, prepared, context):
        result = super().calculate(prepared, context)
        bad = result.contributions[0].model_copy(update={"unit": "fraction"})
        return result.model_copy(update={"contributions": [bad]})


class WrongDrawCountModel(CashModel):
    """Contributes fewer realisations than the scenario set has."""

    model_id = "minimal.wrong_draw_count.v1"

    def calculate(self, prepared, context):
        result = super().calculate(prepared, context)
        contribution = result.contributions[0]
        bad = contribution.model_copy(update={"draws": contribution.draws[:1]})
        return result.model_copy(update={"contributions": [bad]})


class IdentityMismatchModel(CashModel):
    """Reports another position's identity."""

    model_id = "minimal.identity_mismatch.v1"

    def calculate(self, prepared, context):
        result = super().calculate(prepared, context)
        return result.model_copy(update={"position_id": "not-" + result.position_id})


class DetailsSchema(BaseModel):
    reason: str


class BadDetailsModel(CashModel):
    """Declares a details schema its own output violates."""

    model_id = "minimal.bad_details.v1"
    details_schema = DetailsSchema

    def calculate(self, prepared, context):
        result = super().calculate(prepared, context)
        return result.model_copy(update={"details": {"unexpected": "field"}})


class RaisingModel(CashModel):
    """Raises instead of returning a result."""

    model_id = "minimal.raising.v1"

    def calculate(self, prepared, context):
        raise RuntimeError("boom")


def type_spec(*, issuer_required: bool = True, default_model: str = MODEL_ID) -> InstrumentTypeSpec:
    return InstrumentTypeSpec(
        type_id=TYPE_ID,
        label="Наличные (тест)",
        terms_schema=MinimalTerms,
        position_schema=MinimalPosition,
        default_model=default_model,
        schema_version="1",
        issuer_required=issuer_required,
    )


def metric_specs() -> tuple[MetricSpec, ...]:
    return (
        MetricSpec(metric_id=VALUE_METRIC, label="Value", unit=BASE_MONEY, kind="value"),
        MetricSpec(metric_id=PNL_METRIC, label="PnL", unit=BASE_MONEY, kind="distribution"),
    )


def make_plugin(
    *,
    models=None,
    issuer_required: bool = True,
    default_model: str = MODEL_ID,
) -> Plugin:
    """A minimal plugin declaration; pass ``models`` to add broken variants alongside the good
    one (the default model, ``CashModel``, is always present so ``default_model`` resolves;
    passing a model with the same id, e.g. another ``CashModel``, replaces it)."""
    by_id = {CashModel().model_id: CashModel()}
    for model in models or ():
        by_id[model.model_id] = model
    all_models = tuple(by_id.values())
    return Plugin(
        plugin_id=PLUGIN_ID,
        version=PLUGIN_VERSION,
        sdk=">=1.0,<2.0",
        label="Minimal test plugin",
        instrument_types=(type_spec(issuer_required=issuer_required, default_model=default_model),),
        models=all_models,
        metrics=metric_specs(),
    )


plugin = make_plugin()
