"""msa.platform.registry: build() validation, lookups, discover() and installed()."""

import pytest
from pydantic import BaseModel

from msa.contracts.domain import Instrument, Position, PositionContext
from msa.platform.registry import (
    PluginError,
    UnknownInstrumentType,
    UnknownModel,
    build,
    discover,
    installed,
    registry,
)
from msa.plugin_sdk.model import CalculationModel, DataRequirements, Diagnostics
from msa.plugin_sdk.plugin import Plugin
from msa.plugin_sdk.specs import (
    ActionSpec,
    FactorSpec,
    InstrumentTypeSpec,
    MetricSpec,
    RecommendationRule,
    ResultView,
    SliceSpec,
)


class Terms(BaseModel):
    pass


class Params(BaseModel):
    pass


class StubModel(CalculationModel):
    """A minimal concrete model for exercising the registry's cross-reference checks."""

    def __init__(self, model_id, instrument_types, version="1.0.0", **kwargs):
        self.model_id = model_id
        self.version = version
        self.label = model_id
        self.instrument_types = tuple(instrument_types)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def requirements(self, position, options):
        return DataRequirements()

    def validate(self, prepared):
        return Diagnostics()

    def calculate(self, prepared, context):
        raise NotImplementedError


def type_spec(type_id="stub.cash", default_model="stub.model.v1", **overrides):
    values = dict(
        type_id=type_id,
        label="Stub",
        terms_schema=Terms,
        position_schema=Params,
        default_model=default_model,
    )
    values.update(overrides)
    return InstrumentTypeSpec(**values)


def model(model_id="stub.model.v1", instrument_types=("stub.cash",), **kwargs):
    return StubModel(model_id, instrument_types, **kwargs)


def plugin(plugin_id="stub", **overrides):
    values = dict(
        plugin_id=plugin_id,
        version="1.0.0",
        sdk=">=1.0,<2.0",
        label="Stub plugin",
        instrument_types=(type_spec(),),
        models=(model(),),
    )
    values.update(overrides)
    return Plugin(**values)


def test_build_accepts_a_minimal_valid_plugin():
    reg = build([plugin()])
    assert "stub.cash" in reg.instrument_types
    assert "stub.model.v1" in reg.models


# -- id / version / sdk checks --------------------------------------------------------


def test_build_rejects_bad_plugin_id_pattern():
    with pytest.raises(PluginError, match="lower_snake_case"):
        build([plugin(plugin_id="Not-Valid")])


def test_build_rejects_duplicate_plugin_id():
    with pytest.raises(PluginError, match="declared twice"):
        build([plugin(), plugin()])


def test_build_rejects_bad_version():
    with pytest.raises(PluginError, match="is not x.y.z"):
        build([plugin(version="not-a-version")])


def test_build_rejects_incompatible_sdk_range():
    with pytest.raises(PluginError, match="requires SDK"):
        build([plugin(sdk=">=99.0")])


def test_build_rejects_malformed_sdk_range():
    with pytest.raises(PluginError, match="sdk range"):
        build([plugin(sdk="not-a-range")])


# -- namespacing and duplicate identifiers --------------------------------------------


def test_build_rejects_metric_not_namespaced_to_plugin():
    bad_metric = MetricSpec(metric_id="not_namespaced", label="M", unit="fraction")
    with pytest.raises(PluginError, match="must start with 'stub.'"):
        build([plugin(metrics=(bad_metric,))])


def test_build_accepts_namespaced_metric():
    reg = build([plugin(metrics=(MetricSpec(metric_id="stub.m", label="M", unit="fraction"),))])
    assert "stub.m" in reg.metrics


def test_build_rejects_duplicate_identifier_across_plugins():
    a = plugin(plugin_id="a", metrics=(MetricSpec(metric_id="a.m", label="M", unit="fraction"),))
    b = plugin(
        plugin_id="b",
        instrument_types=(),
        models=(),
        metrics=(MetricSpec(metric_id="a.m", label="M2", unit="fraction"),),
    )
    with pytest.raises(PluginError, match="is already declared by a"):
        build([a, b])


def test_instrument_type_id_is_not_namespaced_by_convention():
    # Instrument type ids are declared with spaced=False; an unnamespaced id is fine.
    plain_type = type_spec(type_id="plain_type", default_model="stub.model.v1")
    reg = build(
        [
            plugin(
                instrument_types=(plain_type,),
                models=(model(instrument_types=("plain_type",)),),
            )
        ]
    )
    assert "plain_type" in reg.instrument_types


# -- default model checks --------------------------------------------------------------


def test_build_rejects_missing_default_model():
    with pytest.raises(PluginError, match="default model 'nope' is not declared"):
        build([plugin(instrument_types=(type_spec(default_model="nope"),))])


def test_build_rejects_default_model_not_serving_the_type():
    other = model(model_id="stub.other.v1", instrument_types=("other.type",))
    with pytest.raises(PluginError, match="does not calculate it"):
        build(
            [
                plugin(
                    instrument_types=(type_spec(default_model="stub.other.v1"),),
                    models=(other,),
                )
            ]
        )


# -- model cross-references -------------------------------------------------------------


def test_build_rejects_model_calculating_undeclared_instrument_type():
    with pytest.raises(PluginError, match="calculates undeclared instrument type"):
        build(
            [
                plugin(
                    instrument_types=(),
                    models=(model(instrument_types=("stub.cash",)),),
                )
            ]
        )


def test_build_rejects_model_reporting_undeclared_metric():
    with pytest.raises(PluginError, match="reports undeclared metric"):
        build([plugin(models=(model(metrics=("stub.missing",)),))])


def test_build_rejects_model_reading_undeclared_slice():
    with pytest.raises(PluginError, match="contributes to undeclared slice"):
        build([plugin(models=(model(slices=("stub.missing_slice",)),))])


def test_build_rejects_model_reading_undeclared_factor():
    with pytest.raises(PluginError, match="reads undeclared factor"):
        build([plugin(models=(model(factors=("stub.missing_factor",)),))])


def test_build_rejects_required_metrics_not_among_metrics():
    with pytest.raises(PluginError, match="required metrics must be among its metrics"):
        build(
            [
                plugin(
                    metrics=(MetricSpec(metric_id="stub.m", label="M", unit="fraction"),),
                    models=(model(metrics=("stub.m",), required_metrics=("stub.other",)),),
                )
            ]
        )


def test_build_accepts_model_with_declared_metrics_slices_and_factors():
    reg = build(
        [
            plugin(
                metrics=(MetricSpec(metric_id="stub.m", label="M", unit="fraction"),),
                factors=(
                    FactorSpec(
                        factor_id="stub.f",
                        label="F",
                        unit="fraction",
                        scope="global",
                        application="relative",
                        quantity="relative_change",
                    ),
                ),
                slices=(
                    SliceSpec(
                        slice_id="stub.s",
                        label="S",
                        measure_label="loss",
                        exposure_basis="ead",
                        exposure_label="EAD",
                    ),
                ),
                models=(
                    model(
                        metrics=("stub.m",),
                        required_metrics=("stub.m",),
                        slices=("stub.s",),
                        factors=("stub.f",),
                    ),
                ),
            )
        ]
    )
    assert reg.models["stub.model.v1"].required_metrics == ("stub.m",)


# -- rules ------------------------------------------------------------------------------


def test_build_rejects_rule_reading_undeclared_observation():
    rule = RecommendationRule(
        rule_id="stub.r1",
        label="R1",
        observation="stub.missing",
        operator="ge",
        threshold=1.0,
        actions=("stub.a1",),
    )
    with pytest.raises(PluginError, match="reads undeclared observation"):
        build([plugin(rules=(rule,), actions=(ActionSpec("stub.a1", "A1"),))])


def test_build_rejects_rule_recommending_undeclared_action():
    rule = RecommendationRule(
        rule_id="stub.r1",
        label="R1",
        observation="stub.obs",
        operator="ge",
        threshold=1.0,
        actions=("stub.missing_action",),
    )
    with pytest.raises(PluginError, match="recommends undeclared action"):
        build([plugin(rules=(rule,), observations={"stub.obs": lambda r, c: None})])


def test_build_accepts_valid_rule():
    rule = RecommendationRule(
        rule_id="stub.r1",
        label="R1",
        observation="stub.obs",
        operator="ge",
        threshold=1.0,
        actions=("stub.a1",),
    )
    reg = build(
        [
            plugin(
                rules=(rule,),
                actions=(ActionSpec("stub.a1", "A1"),),
                observations={"stub.obs": lambda r, c: None},
            )
        ]
    )
    assert "stub.r1" in reg.rules


# -- views ------------------------------------------------------------------------------


def test_build_rejects_view_showing_undeclared_instrument_type():
    view = ResultView(view_id="stub.v1", instrument_types=("nope",))
    with pytest.raises(PluginError, match="shows undeclared instrument type"):
        build([plugin(views=(view,))])


def test_build_rejects_view_block_showing_undeclared_metric():
    from msa.plugin_sdk.specs import ViewBlock

    view = ResultView(
        view_id="stub.v1",
        instrument_types=("stub.cash",),
        blocks=(ViewBlock(kind="metric", metric_ids=("stub.missing",)),),
    )
    with pytest.raises(PluginError, match="shows undeclared metric"):
        build([plugin(views=(view,))])


def test_build_rejects_view_summary_metric_undeclared():
    view = ResultView(
        view_id="stub.v1",
        instrument_types=("stub.cash",),
        summary_metrics=("stub.missing",),
    )
    with pytest.raises(PluginError, match="shows undeclared metric"):
        build([plugin(views=(view,))])


def test_build_accepts_valid_view():
    view = ResultView(view_id="stub.v1", instrument_types=("stub.cash",))
    reg = build([plugin(views=(view,))])
    assert "stub.v1" in reg.views


# -- metric unit ---------------------------------------------------------------------


def test_build_rejects_bad_metric_unit():
    with pytest.raises(PluginError, match="unit"):
        build([plugin(metrics=(MetricSpec(metric_id="stub.m", label="M", unit="kilograms"),))])


def test_build_accepts_base_money_metric_unit():
    from msa.plugin_sdk.specs import BASE_MONEY

    reg = build([plugin(metrics=(MetricSpec(metric_id="stub.m", label="M", unit=BASE_MONEY),))])
    assert reg.metrics["stub.m"].unit == BASE_MONEY


def test_build_rejects_bad_slice_coverage_limit():
    with pytest.raises(PluginError, match="coverage limit"):
        build(
            [
                plugin(
                    slices=(
                        SliceSpec(
                            slice_id="stub.s",
                            label="S",
                            measure_label="loss",
                            exposure_basis="ead",
                            exposure_label="EAD",
                            coverage_limit=1.5,
                        ),
                    )
                )
            ]
        )


# -- all problems collected in one error ----------------------------------------------


def test_build_collects_every_problem_in_one_error():
    with pytest.raises(PluginError) as excinfo:
        build([plugin(plugin_id="Bad-Id", version="bad", sdk="bad-range")])
    problems = excinfo.value.problems
    assert len(problems) >= 3
    assert any("lower_snake_case" in p for p in problems)
    assert any("is not x.y.z" in p for p in problems)
    assert any("sdk range" in p for p in problems)


# -- Registry lookups ------------------------------------------------------------------


def make_registry():
    other_model = model(model_id="stub.other.v1", instrument_types=("stub.cash",))
    return build([plugin(models=(model(), other_model))])


def position_context(model_id=None):
    instrument = Instrument(instrument_id="I1", instrument_type="stub.cash", name="I1")
    return PositionContext(
        portfolio_id="PF1",
        position=Position(position_id="POS1", instrument_id="I1", model_id=model_id),
        instrument=instrument,
        issuer=None,
    )


def test_registry_instrument_type_lookup():
    reg = make_registry()
    assert reg.instrument_type("stub.cash").type_id == "stub.cash"


def test_registry_instrument_type_unknown_raises():
    reg = make_registry()
    with pytest.raises(UnknownInstrumentType):
        reg.instrument_type("nope")


def test_registry_model_lookup():
    reg = make_registry()
    assert reg.model("stub.model.v1").model_id == "stub.model.v1"


def test_registry_model_unknown_raises():
    reg = make_registry()
    with pytest.raises(UnknownModel):
        reg.model("nope")


def test_model_for_uses_default_when_position_names_none():
    reg = make_registry()
    m = reg.model_for(position_context())
    assert m.model_id == "stub.model.v1"


def test_model_for_uses_explicit_position_model_id():
    reg = make_registry()
    m = reg.model_for(position_context(model_id="stub.other.v1"))
    assert m.model_id == "stub.other.v1"


def test_model_for_raises_when_explicit_model_does_not_serve_the_type():
    other_type_model = model(model_id="stub.wrong.v1", instrument_types=("other.type",))
    reg = build(
        [
            plugin(models=(model(), other_type_model)),
            plugin(
                plugin_id="other2",
                instrument_types=(
                    type_spec(
                        type_id="other.type",
                        default_model="stub.wrong.v1",
                    ),
                ),
                models=(),
            ),
        ]
    )
    with pytest.raises(UnknownModel, match="does not calculate"):
        reg.model_for(position_context(model_id="stub.wrong.v1"))


def test_models_for_type_returns_every_model_serving_it():
    reg = make_registry()
    ids = {m.model_id for m in reg.models_for_type("stub.cash")}
    assert ids == {"stub.model.v1", "stub.other.v1"}


def test_view_for_returns_matching_view_or_none():
    view = ResultView(view_id="stub.v1", instrument_types=("stub.cash",))
    reg = build([plugin(views=(view,))])
    assert reg.view_for("stub.cash").view_id == "stub.v1"
    assert reg.view_for("no.such.type") is None


def test_flag_wording_merges_every_plugin():
    a = plugin(plugin_id="a", instrument_types=(), models=(), flags={"a.flag": "A"})
    b = plugin(plugin_id="b", instrument_types=(), models=(), flags={"b.flag": "B"})
    reg = build([a, b])
    assert reg.flag_wording() == {"a.flag": "A", "b.flag": "B"}


def test_run_options_merges_every_plugin_for_a_scope():
    a = plugin(
        plugin_id="a", instrument_types=(), models=(), run_options=lambda scope: {"a.opt": scope}
    )
    b = plugin(
        plugin_id="b",
        instrument_types=(),
        models=(),
        run_options=lambda scope: {"b.opt": scope + "!"},
    )
    reg = build([a, b])
    assert reg.run_options("demo") == {"a.opt": "demo", "b.opt": "demo!"}


def _namespaced(plugin_id):
    return plugin(
        plugin_id=plugin_id,
        instrument_types=(type_spec(default_model=f"{plugin_id}.model.v1"),),
        models=(model(model_id=f"{plugin_id}.model.v1"),),
    )


def test_versions_reports_sdk_and_every_plugin():
    reg = make_registry()
    versions = reg.versions()
    assert versions["sdk"]
    assert versions["stub"] == "1.0.0"


# -- discover() and installed() ---------------------------------------------------------


def test_discover_finds_the_real_market_and_credit_plugins():
    plugins = discover()
    ids = {p.plugin_id for p in plugins}
    assert {"market", "credit"} <= ids


def test_installed_adds_an_extra_plugin_and_restores_previous_registry():
    before = registry()
    with installed(_namespaced("temp_extra")) as reg:
        assert "temp_extra" in reg.plugins
        assert registry() is reg
    after = registry()
    assert after is before
    assert "temp_extra" not in after.plugins


def test_installed_restores_registry_even_after_an_error():
    before = registry()
    with pytest.raises(PluginError):
        with installed(plugin(plugin_id="Bad-Id")):
            pass
    assert registry() is before
