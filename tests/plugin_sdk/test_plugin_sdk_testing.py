"""msa.plugin_sdk.testing: check_plugin() findings for deliberately broken declarations."""

from dataclasses import replace

from msa.plugin_sdk.plugin import Plugin
from msa.plugin_sdk.specs import EditorField, EditorGroup
from msa.plugin_sdk.testing import Finding, check_plugin

from tests import minimal_plugin as mp


class NoRequiredMetricsModel(mp.CashModel):
    model_id = "minimal.no_required_metrics.v1"
    required_metrics = ()


def plugin_with(*, editor=(), models=None, demo=None):
    type_spec = replace(mp.type_spec(default_model=mp.MODEL_ID), editor=editor)
    return Plugin(
        plugin_id="minimal",
        version="1.0.0",
        sdk=">=1.0,<2.0",
        label="T",
        instrument_types=(type_spec,),
        models=models if models is not None else (mp.CashModel(),),
        metrics=mp.metric_specs(),
        demo=demo,
    )


# -- Finding.__str__ ------------------------------------------------------------------------


def test_finding_str_includes_case_when_present():
    f = Finding("plugin_a", "outputs", "bad thing", case="case1")
    assert str(f) == "plugin_a [case1] outputs: bad thing"


def test_finding_str_without_case():
    f = Finding("plugin_a", "outputs", "bad thing")
    assert str(f) == "plugin_a outputs: bad thing"


# -- _declarations findings, exercised through check_plugin ---------------------------------


def test_check_plugin_flags_editor_field_with_unknown_target():
    group = EditorGroup(
        group_id="g",
        title="G",
        fields=(EditorField(name="x", label="X", target="not_a_valid_target"),),
    )
    plugin = plugin_with(editor=(group,))
    findings = check_plugin(plugin)
    assert any(f.check == "editor" and "unknown target" in f.message for f in findings)


def test_check_plugin_flags_editor_field_with_unknown_unit():
    group = EditorGroup(
        group_id="g",
        title="G",
        fields=(EditorField(name="x", label="X", target="position", unit="kilograms"),),
    )
    plugin = plugin_with(editor=(group,))
    findings = check_plugin(plugin)
    assert any(f.check == "units" and "unknown unit" in f.message for f in findings)


def test_check_plugin_accepts_snapshot_prefixed_target_and_base_money_unit():
    group = EditorGroup(
        group_id="g",
        title="G",
        fields=(EditorField(name="x", label="X", target="snapshot:fx_rate", unit="base_money"),),
    )
    plugin = plugin_with(editor=(group,))
    findings = check_plugin(plugin)
    assert not any(f.check in ("editor", "units") for f in findings)


def test_check_plugin_flags_model_declaring_no_required_metric():
    plugin = plugin_with(models=(NoRequiredMetricsModel(),))
    findings = check_plugin(plugin)
    assert any(
        f.check == "outputs" and "declares no required metric" in f.message for f in findings
    )


# -- demo case requirement --------------------------------------------------------------------


def test_check_plugin_requires_a_demo_case_for_an_asset_plugin():
    plugin = plugin_with(demo=None)
    findings = check_plugin(plugin)
    assert any(f.check == "demo" for f in findings)


def test_check_plugin_with_no_instrument_types_and_no_demo_is_fine():
    plugin = Plugin(
        plugin_id="empty",
        version="1.0.0",
        sdk=">=1.0,<2.0",
        label="Empty",
    )
    assert check_plugin(plugin) == []
