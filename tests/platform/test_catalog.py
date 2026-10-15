"""msa.platform.catalog: asset_types(), models(), workflows(), enabled_agents()."""

from msa.platform.catalog import asset_types, enabled_agents, models, workflows
from msa.platform.registry import build, registry

from tests import minimal_plugin as mp


def _registry():
    return build([mp.plugin, mp.MARKET_PLUGIN])


# -- enabled_agents() ---------------------------------------------------------------------


def test_enabled_agents_empty_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("MSA_AGENT_PLUGINS", raising=False)
    assert enabled_agents() == set()


def test_enabled_agents_parses_comma_separated_list(monkeypatch):
    monkeypatch.setenv("MSA_AGENT_PLUGINS", "research.explain, other.agent ,")
    assert enabled_agents() == {"research.explain", "other.agent"}


def test_enabled_agents_ignores_blank_entries(monkeypatch):
    monkeypatch.setenv("MSA_AGENT_PLUGINS", ",, ,")
    assert enabled_agents() == set()


# -- asset_types() ------------------------------------------------------------------------


def test_asset_types_includes_the_minimal_type():
    reg = _registry()
    catalog = asset_types(reg)
    types = {t["asset_type"]: t for t in catalog["types"]}
    assert mp.TYPE_ID in types
    entry = types[mp.TYPE_ID]
    assert entry["plugin_id"] == mp.PLUGIN_ID
    assert entry["default_model"] == mp.MODEL_ID
    assert entry["issuer_required"] is True
    assert mp.VALUE_METRIC in entry["metrics"]
    assert "properties" in entry["terms_schema"]
    assert "properties" in entry["position_schema"]


def test_asset_types_top_level_shape_has_plugins_metrics_units():
    reg = _registry()
    catalog = asset_types(reg)
    assert {p["plugin_id"] for p in catalog["plugins"]} == {"minimal", "market"}
    assert mp.VALUE_METRIC in catalog["metrics"]
    assert "RUB" in catalog["units"]["currencies"]
    assert "fraction" in catalog["units"]["plain"]
    assert catalog["sdk_version"]


def test_asset_types_on_the_real_registry_every_type_has_a_model():
    catalog = asset_types(registry())
    for entry in catalog["types"]:
        assert entry["models"], entry["asset_type"]
        assert entry["default_model"] in {m["model_id"] for m in entry["models"]}


# -- models() -------------------------------------------------------------------------------


def test_models_lists_every_model_with_details_schema_key():
    reg = _registry()
    described = {item["model_id"]: item for item in models(reg)}
    assert mp.MODEL_ID in described
    assert "details_schema" in described[mp.MODEL_ID]
    assert "input_schema" not in described[mp.MODEL_ID]


# -- workflows() ----------------------------------------------------------------------------


def test_workflows_marks_agents_enabled_by_default_or_via_env(monkeypatch):
    reg = registry()
    monkeypatch.delenv("MSA_AGENT_PLUGINS", raising=False)
    specs = workflows(reg)
    assert specs, "the real registry declares at least one workflow"
    for spec in specs:
        for agent in spec["agents"]:
            assert agent["enabled"] == agent_enabled_by_default(reg, agent["agent_id"])


def agent_enabled_by_default(reg, agent_id):
    return reg.agents[agent_id].enabled_by_default


def test_workflows_respects_explicit_enabled_set():
    reg = registry()
    non_core = [a for a in reg.agents.values() if not a.core]
    if not non_core:
        return
    target = non_core[0].agent_id
    specs = workflows(reg, enabled={target})
    found = any(
        agent["agent_id"] == target and agent["enabled"]
        for spec in specs
        for agent in spec["agents"]
    )
    assert found
