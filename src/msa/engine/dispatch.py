"""The general dispatcher: one position through its model, with no branch on its type.

``prepare`` validates the instrument and position against their type's schemas, asks the
model for its requirements, resolves them against the snapshot and lets the model judge
the result. ``calculate`` runs the model on the approved scenario set and checks what it
returned against the model's declaration: identity, metrics and units, required outputs,
contributions and their array shapes, and the plugin's own result schema. A model that
breaks its declaration does not reach the portfolio: its position stays in the run as
``invalid`` with the reason.
"""

from pydantic import ValidationError

from msa.contracts.domain import PositionContext
from msa.contracts.result import CalculationResult, DataQuality, Diagnostic
from msa.contracts.units import money
from msa.platform.registry import Registry, UnknownInstrumentType, UnknownModel
from msa.plugin_sdk.model import (
    CalculationContext,
    DataRequirements,
    Diagnostics,
    PreparedInputs,
    RunOptions,
)
from msa.plugin_sdk.specs import BASE_MONEY
from msa.version import code_sha256

from .snapshot import SnapshotIndex, resolve


def resolved_unit(unit: str, base_currency: str) -> str:
    return money(base_currency) if unit == BASE_MONEY else unit


def schema_problems(context: PositionContext, registry: Registry) -> list[Diagnostic]:
    """Instrument terms and position params against their type's versioned schemas."""
    try:
        spec = registry.instrument_type(context.instrument.instrument_type)
    except UnknownInstrumentType as exc:
        return [Diagnostic(code="unknown_instrument_type", severity="error", message=str(exc))]
    problems = []
    for part, schema, value, version in (
        ("terms", spec.terms_schema, context.instrument.terms, context.instrument.schema_version),
        ("params", spec.position_schema, context.position.params, context.position.schema_version),
    ):
        if version != spec.schema_version:
            problems.append(
                Diagnostic(
                    code="schema_version_mismatch",
                    severity="error",
                    path=f"/{part}",
                    message=(
                        f"{part} follow schema {version}, the plugin reads {spec.schema_version}"
                    ),
                )
            )
            continue
        try:
            schema.model_validate(value)
        except ValidationError as exc:
            for error in exc.errors():
                problems.append(
                    Diagnostic(
                        code="schema",
                        severity="error",
                        path="/" + "/".join([part, *(str(p) for p in error["loc"])]),
                        message=error["msg"],
                    )
                )
    if spec.issuer_required and context.issuer is None:
        problems.append(
            Diagnostic(code="issuer_missing", severity="error", message="the type needs an issuer")
        )
    return problems


def requirements(context: PositionContext, options: RunOptions, registry: Registry):
    """``(model, requirements)`` of a position, or ``(None, None)`` when it has no model."""
    try:
        model = registry.model_for(context)
    except (UnknownInstrumentType, UnknownModel):
        return None, None
    return model, model.requirements(context, options)


def prepare(
    context: PositionContext,
    options: RunOptions,
    index: SnapshotIndex,
    registry: Registry,
    *,
    sector_of,
) -> tuple[PreparedInputs | None, Diagnostics]:
    """The prepared inputs of one position and what its model found about them."""
    problems = schema_problems(context, registry)
    try:
        model = registry.model_for(context)
    except (UnknownInstrumentType, UnknownModel) as exc:
        problems.append(Diagnostic(code="no_model", severity="error", message=str(exc)))
        return None, Diagnostics(items=problems, blocked_status="invalid")
    if problems:
        return None, Diagnostics(items=problems, blocked_status="invalid")
    needs = model.requirements(context, options)
    data, missing = resolve(needs, index, as_of=options.as_of, sector_of=sector_of)
    prepared = PreparedInputs(
        context=context,
        model_id=model.model_id,
        as_of=options.as_of,
        horizon=options.horizon,
        snapshot_id=index.snapshot_id,
        data=data,
        missing=missing,
        requirements=needs,
        options=options.options,
    )
    diagnostics = with_required_data(model.validate(prepared), needs, missing)
    return prepared, diagnostics


def with_required_data(diagnostics: Diagnostics, needs, missing) -> Diagnostics:
    """A required input the snapshot lacks stops the position unless the model said so."""
    stated = {item.code for item in diagnostics.items}
    extra = []
    for requirement in needs.data:
        if not requirement.required or requirement.key not in missing:
            continue
        late = missing[requirement.key] == "dated_after_as_of"
        code = ("data_dated_after_as_of:" if late else "data_missing:") + requirement.key
        if code not in stated:
            extra.append(
                Diagnostic(
                    code=code,
                    severity="error",
                    message=requirement.purpose or requirement.kind,
                    path=f"/data/{requirement.key}",
                )
            )
    if not extra:
        return diagnostics
    update = {"items": [*diagnostics.items, *extra]}
    if not diagnostics.blocking:
        update["blocked_status"] = "needs_review"
    return diagnostics.model_copy(update=update)


def not_run(
    context: PositionContext,
    diagnostics: Diagnostics,
    registry: Registry,
    *,
    as_of,
    horizon,
    seed,
    scenario_id=None,
    snapshot_id=None,
    macro_draws_sha256=None,
    model_id=None,
) -> CalculationResult:
    """A position that was not calculated stays in the run with its reason, without numbers."""
    model = None
    try:
        model = registry.model(model_id) if model_id else registry.model_for(context)
    except (UnknownInstrumentType, UnknownModel):
        pass
    plugin = registry.plugins.get(registry.owner.get(model.model_id)) if model else None
    blocking = diagnostics.blocking or [
        Diagnostic(code="not_calculated", severity="error", message="the position was not run")
    ]
    return CalculationResult(
        position_id=context.position_id,
        instrument_id=context.instrument.instrument_id,
        instrument_type=context.instrument.instrument_type,
        plugin_id=plugin.plugin_id if plugin else "none",
        plugin_version=plugin.version if plugin else "none",
        model_id=model.model_id if model else "none",
        model_version=model.version if model else "none",
        as_of=as_of,
        horizon=horizon,
        seed=seed,
        base_currency=context.base_currency,
        scenario_id=scenario_id,
        snapshot_id=snapshot_id,
        macro_draws_sha256=macro_draws_sha256,
        execution="not_run",
        applicability="not_applicable" if diagnostics.blocked_status == "invalid" else "limited",
        data_quality=diagnostics.data_quality,
        status=diagnostics.blocked_status,
        flags=[item.code for item in blocking],
        diagnostics=diagnostics.items,
        code_sha256=code_sha256(),
    )


def calculate(
    prepared: PreparedInputs,
    diagnostics: Diagnostics,
    context: CalculationContext,
    registry: Registry,
) -> CalculationResult:
    """The model's result, checked against its declaration; a broken one is ``invalid``."""
    model = registry.model(prepared.model_id)
    ids = dict(
        as_of=context.as_of,
        horizon=context.horizon,
        seed=context.seed,
        scenario_id=context.scenario.scenario_id,
        snapshot_id=context.snapshot_id,
        macro_draws_sha256=context.scenario.macro_draws_sha256,
        model_id=model.model_id,
    )
    if diagnostics.blocking:
        return not_run(prepared.context, diagnostics, registry, **ids)
    try:
        result = model.calculate(prepared, context)
        problems = output_problems(result, prepared, context, registry)
    except Exception as exc:  # noqa: BLE001 - one position must not end the run
        problems = [
            Diagnostic(
                code=f"model_error:{type(exc).__name__}",
                severity="error",
                message=str(exc)[:500],
            )
        ]
    if problems:
        failed = Diagnostics(
            items=[*diagnostics.items, *problems],
            data_quality=diagnostics.data_quality,
            blocked_status="invalid",
        )
        broken = not_run(prepared.context, failed, registry, **ids)
        return broken.model_copy(update={"execution": "failed"})
    # Warnings of the input check travel with the result.
    known = {(item.code, item.path) for item in result.diagnostics}
    extra = [item for item in diagnostics.items if (item.code, item.path) not in known]
    return result.model_copy(update={"diagnostics": [*extra, *result.diagnostics]})


def output_problems(result, prepared, context, registry) -> list[Diagnostic]:
    """How a result departs from its model's declaration (audit finding A5)."""
    model = registry.model(prepared.model_id)
    plugin = registry.plugin_of(model.model_id)
    problems = []

    def fail(code, message, path=""):
        problems.append(
            Diagnostic(code=f"output:{code}", severity="error", message=message, path=path)
        )

    expected = {
        "position_id": prepared.context.position_id,
        "instrument_id": prepared.context.instrument.instrument_id,
        "instrument_type": prepared.context.instrument.instrument_type,
        "model_id": model.model_id,
        "model_version": model.version,
        "plugin_id": plugin.plugin_id,
        "plugin_version": plugin.version,
        "as_of": context.as_of,
        "horizon": context.horizon,
        "seed": context.seed,
        "base_currency": context.base_currency,
    }
    for name, value in expected.items():
        if getattr(result, name) != value:
            fail("identity", f"{name} is {getattr(result, name)!r}, expected {value!r}", f"/{name}")
    if result.execution == "completed" and result.scenario_id != context.scenario.scenario_id:
        fail("identity", "the result names another scenario set", "/scenario_id")
    for metric_id, value in result.metrics.items():
        if metric_id not in model.metrics:
            fail(
                "metric",
                f"{metric_id} is not a declared metric of the model",
                f"/metrics/{metric_id}",
            )
            continue
        spec = registry.metrics[metric_id]
        unit = resolved_unit(spec.unit, context.base_currency)
        if value.unit != unit:
            fail(
                "unit", f"{metric_id} is in {value.unit}, declared {unit}", f"/metrics/{metric_id}"
            )
        if spec.kind == "distribution" and value.quantiles is None:
            fail("shape", f"{metric_id} is declared a distribution", f"/metrics/{metric_id}")
    if result.execution == "completed":
        for metric_id in model.required_metrics:
            if metric_id not in result.metrics:
                fail("missing_metric", f"required metric {metric_id} is absent", "/metrics")
    size = context.scenario.replicates * context.scenario.points
    for index, item in enumerate(result.contributions):
        path = f"/contributions/{index}"
        if item.slice_id not in model.slices:
            fail("slice", f"{item.slice_id} is not a declared slice of the model", path)
            continue
        unit = resolved_unit(registry.slices[item.slice_id].unit, context.base_currency)
        if item.unit != unit:
            fail(
                "unit", f"contribution to {item.slice_id} is in {item.unit}, slice in {unit}", path
            )
        if item.enters and (item.draws is None or len(item.draws) != size):
            fail("shape", f"contribution to {item.slice_id} needs {size} realisations", path)
    if model.details_schema is not None and result.details:
        try:
            model.details_schema.model_validate(result.details)
        except ValidationError as exc:
            fail("details", str(exc.errors()[0]["msg"]), "/details")
    return problems


def data_quality_level(score: float | None) -> DataQuality:
    if score is None:
        return DataQuality()
    level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
    return DataQuality(score=score, level=level)


__all__ = [
    "DataRequirements",
    "calculate",
    "data_quality_level",
    "not_run",
    "output_problems",
    "prepare",
    "requirements",
    "resolved_unit",
    "schema_problems",
]
