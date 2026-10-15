"""msa.engine.model_catalog: run_model()/ScenarioMismatch and describe_model()/list_models()."""

import pytest

from msa.engine.model_catalog import (
    ModelRunInput,
    ScenarioMismatch,
    ScenarioPayload,
    describe_model,
    list_models,
    run_model,
)
from msa.engine.scenario_set import Realisations, scenario_set_from_parameters
from msa.platform.registry import build, registry
from tests import engine_helpers as h
from tests import minimal_plugin as mp


@pytest.fixture
def test_registry():
    return build([mp.plugin, mp.MARKET_PLUGIN])


def _payload(prepared, diagnostics, *, seed=1, points=h.POINTS, replicates=h.REPLICATES):
    scenario_set = scenario_set_from_parameters(
        {"dummy": {"kind": "point", "value": 0.0, "unit": "fraction"}},
        points=points,
        replicates=replicates,
    ).with_idiosyncratic(diagnostics.idiosyncratic)
    view = Realisations(scenario_set=scenario_set, seed=seed, as_of=h.AS_OF, horizon=12)
    scenario = ScenarioPayload(
        spec=scenario_set.spec(),
        seed=seed,
        as_of=h.AS_OF,
        horizon=12,
        macro_draws_sha256=view.macro_draws_sha256,
        scenario_id=view.scenario_id,
    )
    return ModelRunInput(
        prepared=prepared,
        diagnostics=diagnostics,
        scenario=scenario,
        base_currency="RUB",
        snapshot_id="SNAP1",
    )


def _prepared(test_registry, currency="RUB"):
    ctx = h.cash_context(currency=currency)
    options = h.run_options(base_currency="RUB")
    return h.prepare_with(ctx, options, test_registry)


# -- run_model: a normal round trip -----------------------------------------------------


def test_run_model_completes_and_returns_slice_draws(test_registry):
    prepared, diagnostics = _prepared(test_registry)
    payload = _payload(prepared, diagnostics)
    output = run_model(mp.MODEL_ID, payload, registry=test_registry)
    assert output.result.execution == "completed"
    assert output.result.position_id == "POS1"
    assert mp.SLICE_ID in output.draws
    assert len(output.draws[mp.SLICE_ID]) == h.POINTS * h.REPLICATES
    assert len(output.code_sha256) == 64


def test_run_model_accepts_a_plain_dict_payload(test_registry):
    prepared, diagnostics = _prepared(test_registry)
    payload = _payload(prepared, diagnostics)
    dict_payload = payload.model_dump(mode="json")
    output = run_model(mp.MODEL_ID, dict_payload, registry=test_registry)
    assert output.result.execution == "completed"


def test_run_model_rejects_inputs_prepared_for_another_model():
    reg = build([mp.make_plugin(models=(mp.WrongMetricUnitModel(),)), mp.MARKET_PLUGIN])
    prepared, diagnostics = _prepared(reg)
    payload = _payload(prepared, diagnostics)
    with pytest.raises(ValueError, match="were prepared for"):
        run_model("minimal.wrong_metric_unit.v1", payload, registry=reg)


# -- run_model: ScenarioMismatch --------------------------------------------------------


def test_run_model_raises_on_tampered_macro_hash(test_registry):
    prepared, diagnostics = _prepared(test_registry)
    payload = _payload(prepared, diagnostics)
    bad_scenario = payload.scenario.model_copy(update={"macro_draws_sha256": "b" * 64})
    bad_payload = payload.model_copy(update={"scenario": bad_scenario})
    with pytest.raises(ScenarioMismatch):
        run_model(mp.MODEL_ID, bad_payload, registry=test_registry)


def test_run_model_raises_on_tampered_scenario_id(test_registry):
    prepared, diagnostics = _prepared(test_registry)
    payload = _payload(prepared, diagnostics)
    bad_scenario = payload.scenario.model_copy(update={"scenario_id": "c" * 64})
    bad_payload = payload.model_copy(update={"scenario": bad_scenario})
    with pytest.raises(ScenarioMismatch):
        run_model(mp.MODEL_ID, bad_payload, registry=test_registry)


def test_run_model_raises_on_different_seed_than_recorded(test_registry):
    prepared, diagnostics = _prepared(test_registry)
    payload = _payload(prepared, diagnostics, seed=1)
    # A different seed changes the sampled draws, so the recorded hash/id no longer match.
    bad_scenario = payload.scenario.model_copy(update={"seed": 2})
    bad_payload = payload.model_copy(update={"scenario": bad_scenario})
    with pytest.raises(ScenarioMismatch):
        run_model(mp.MODEL_ID, bad_payload, registry=test_registry)


# -- describe_model / list_models --------------------------------------------------------


def test_describe_model_for_the_minimal_model(test_registry):
    described = describe_model(mp.MODEL_ID, registry=test_registry)
    assert described["model_id"] == mp.MODEL_ID
    assert described["plugin_id"] == mp.PLUGIN_ID
    assert set(described["metric_specs"]) == set(mp.CashModel.metrics)
    assert described["metric_specs"][mp.VALUE_METRIC]["unit"] == "base_money"
    assert len(described["code_sha256"]) == 64
    assert "properties" in described["input_schema"]


def test_list_models_is_sorted_and_includes_every_model(test_registry):
    ids = [item["model_id"] for item in list_models(registry=test_registry)]
    assert ids == sorted(ids)
    assert mp.MODEL_ID in ids


def test_describe_model_on_the_real_registry_has_details_schema_key():
    reg = registry()
    for model_id in reg.models:
        described = describe_model(model_id, registry=reg)
        assert described["metric_specs"] or described["metrics"] == []
        assert described["plugin_id"] in reg.plugins
