"""msa.engine.dispatch: the general dispatcher, tested against the minimal plugin."""

from datetime import date

import pytest

from msa.engine.dispatch import calculate, not_run, resolved_unit, schema_problems
from msa.platform.registry import build
from msa.plugin_sdk.specs import BASE_MONEY
from tests import engine_helpers as h
from tests import minimal_plugin as mp


@pytest.fixture
def registry():
    return build([mp.plugin, mp.MARKET_PLUGIN])


@pytest.fixture
def issuer_optional_registry():
    return build([mp.make_plugin(issuer_required=False), mp.MARKET_PLUGIN])


# -- resolved_unit ------------------------------------------------------------------------


def test_resolved_unit_resolves_base_money_to_the_run_currency():
    assert resolved_unit(BASE_MONEY, "USD") == "USD_million"


def test_resolved_unit_leaves_a_plain_unit_untouched():
    assert resolved_unit("fraction", "USD") == "fraction"


# -- schema_problems ------------------------------------------------------------------------


def test_schema_problems_empty_for_a_valid_context(registry):
    ctx = h.cash_context()
    assert schema_problems(ctx, registry) == []


def test_schema_problems_unknown_instrument_type(registry):
    ctx = h.cash_context(instrument_type="no.such.type")
    problems = schema_problems(ctx, registry)
    assert [p.code for p in problems] == ["unknown_instrument_type"]


def test_schema_problems_schema_version_mismatch(registry):
    ctx = h.cash_context(schema_version="2")
    problems = schema_problems(ctx, registry)
    codes = [p.code for p in problems]
    assert codes.count("schema_version_mismatch") == 1
    paths = {p.path for p in problems if p.code == "schema_version_mismatch"}
    assert paths == {"/params"}


def test_schema_problems_schema_error_has_json_pointer_path(registry):
    ctx = h.cash_context(params_override={})  # missing the required `amount` field
    problems = schema_problems(ctx, registry)
    assert any(p.code == "schema" and p.path == "/params/amount" for p in problems)


def test_schema_problems_nested_schema_error_path(registry):
    bad_amount = {"value": "not-a-number", "unit": "RUB_million", "evidence": []}
    ctx = h.cash_context(params_override={"amount": bad_amount})
    problems = schema_problems(ctx, registry)
    paths = [p.path for p in problems if p.code == "schema"]
    assert any(path.startswith("/params/amount/value") for path in paths)


def test_schema_problems_issuer_required_but_missing(registry):
    ctx = h.cash_context(issuer_id=None)
    problems = schema_problems(ctx, registry)
    assert any(p.code == "issuer_missing" for p in problems)


def test_schema_problems_issuer_not_required_and_missing_is_fine(issuer_optional_registry):
    ctx = h.cash_context(issuer_id=None)
    assert schema_problems(ctx, issuer_optional_registry) == []


# -- prepare() ------------------------------------------------------------------------------


def test_prepare_returns_none_and_invalid_on_schema_problems(registry):
    ctx = h.cash_context(schema_version="2")
    prepared, diagnostics = h.prepare_with(ctx, h.run_options(), registry)
    assert prepared is None
    assert diagnostics.blocked_status == "invalid"
    assert diagnostics.blocking


def test_prepare_resolves_declared_requirements(registry):
    ctx = h.cash_context(currency="USD")
    options = h.run_options(base_currency="RUB")
    prepared, diagnostics = h.prepare_with(ctx, options, registry, items=h.fx_snapshot().items)
    assert prepared is not None
    assert prepared.item("fx").values["rate"].value == 90.0
    assert diagnostics.blocking == []


def test_prepare_required_missing_data_adds_data_missing_diagnostic(registry):
    ctx = h.cash_context(currency="USD")
    options = h.run_options(base_currency="RUB")
    prepared, diagnostics = h.prepare_with(ctx, options, registry)
    codes = {d.code for d in diagnostics.items}
    assert "data_missing:fx" in codes
    assert diagnostics.blocked_status == "needs_review"
    assert diagnostics.blocking


def test_prepare_required_data_dated_after_as_of(registry):
    ctx = h.cash_context(currency="USD")
    # The run itself is valued at h.AS_OF; the snapshot may hold later items (its own as_of
    # is later), and prepare() must still refuse to use them for this run.
    options = h.run_options(base_currency="RUB", as_of=h.AS_OF)
    late = h.fx_snapshot(observed_on=date(2027, 1, 1))
    prepared, diagnostics = h.prepare_with(ctx, options, registry, items=late.items)
    codes = {d.code for d in diagnostics.items}
    assert "data_dated_after_as_of:fx" in codes


def test_prepare_same_currency_position_needs_no_fx_requirement(registry):
    ctx = h.cash_context(currency="RUB")
    options = h.run_options(base_currency="RUB")
    prepared, diagnostics = h.prepare_with(ctx, options, registry)
    assert prepared is not None
    assert diagnostics.blocking == []
    assert diagnostics.idiosyncratic  # validate() still declares the position's own shock


def test_prepare_unknown_model_when_type_not_registered():
    registry = build([mp.make_plugin(), mp.MARKET_PLUGIN])
    ctx = h.cash_context(instrument_type="no.such.type")
    prepared, diagnostics = h.prepare_with(ctx, h.run_options(), registry)
    assert prepared is None
    assert diagnostics.blocked_status == "invalid"


# -- not_run() --------------------------------------------------------------------------------


def test_not_run_carries_the_blocking_reason(registry):
    ctx = h.cash_context(currency="USD")
    options = h.run_options(base_currency="RUB")
    _, diagnostics = h.prepare_with(ctx, options, registry)
    result = not_run(ctx, diagnostics, registry, as_of=h.AS_OF, horizon=12, seed=1)
    assert result.execution == "not_run"
    assert result.status == diagnostics.blocked_status
    assert result.metrics == {}
    assert result.contributions == []
    assert "data_missing:fx" in result.flags


def test_not_run_without_a_resolvable_model_uses_none_placeholders():
    registry = build([mp.make_plugin(), mp.MARKET_PLUGIN])
    ctx = h.cash_context(instrument_type="no.such.type")
    _, diagnostics = h.prepare_with(ctx, h.run_options(), registry)
    result = not_run(ctx, diagnostics, registry, as_of=h.AS_OF, horizon=12, seed=1)
    assert result.plugin_id == "none"
    assert result.model_id == "none"


# -- calculate(): blocked diagnostics --------------------------------------------------------


def test_calculate_with_blocking_diagnostics_returns_not_run(registry):
    ctx = h.cash_context(currency="USD")
    options = h.run_options(base_currency="RUB")
    prepared, diagnostics = h.prepare_with(ctx, options, registry)
    calc_ctx = h.calculation_context(diagnostics)
    result = calculate(prepared, diagnostics, calc_ctx, registry)
    assert result.execution == "not_run"


# -- calculate(): a model that raises ----------------------------------------------------------


def test_calculate_model_raising_becomes_failed_invalid():
    registry = build([mp.make_plugin(models=(mp.RaisingModel(),)), mp.MARKET_PLUGIN])
    ctx = h.cash_context(model_id=mp.RaisingModel.model_id)
    prepared, diagnostics = h.prepare_with(ctx, h.run_options(), registry)
    calc_ctx = h.calculation_context(diagnostics)
    result = calculate(prepared, diagnostics, calc_ctx, registry)
    assert result.execution == "failed"
    assert result.status == "invalid"
    assert any(flag.startswith("model_error:RuntimeError") for flag in result.flags)


# -- calculate(): output_problems, one broken contract at a time -------------------------------


def _run(model, *, currency="RUB"):
    registry = build([mp.make_plugin(models=(model,)), mp.MARKET_PLUGIN])
    ctx = h.cash_context(currency=currency, model_id=model.model_id)
    prepared, diagnostics = h.prepare_with(ctx, h.run_options(), registry)
    calc_ctx = h.calculation_context(diagnostics)
    return calculate(prepared, diagnostics, calc_ctx, registry)


def test_output_identity_mismatch_is_rejected():
    result = _run(mp.IdentityMismatchModel())
    assert result.execution == "failed"
    assert result.status == "invalid"
    assert any("output:identity" in f for f in result.flags)


def test_output_undeclared_metric_is_rejected():
    result = _run(mp.UndeclaredMetricModel())
    assert result.execution == "failed"
    assert any("output:metric" in f for f in result.flags)


def test_output_wrong_metric_unit_is_rejected():
    result = _run(mp.WrongMetricUnitModel())
    assert any("output:unit" in f for f in result.flags)


def test_output_unit_check_resolves_base_money_against_run_currency():
    # WrongMetricUnitModel reports minimal.value in "fraction" instead of the resolved
    # BASE_MONEY unit (RUB_million); confirms resolved_unit is applied before comparing.
    result = _run(mp.WrongMetricUnitModel(), currency="RUB")
    messages = [d.message for d in result.diagnostics if d.code == "output:unit"]
    assert any("declared RUB_million" in message for message in messages)


def test_output_distribution_metric_without_quantiles_is_rejected():
    result = _run(mp.DistributionWithoutQuantilesModel())
    assert any("output:shape" in f for f in result.flags)


def test_output_missing_required_metric_is_rejected():
    result = _run(mp.MissingRequiredMetricModel())
    assert any("output:missing_metric" in f for f in result.flags)


def test_output_contribution_to_undeclared_slice_is_rejected():
    result = _run(mp.UndeclaredSliceModel())
    assert any("output:slice" in f for f in result.flags)


def test_output_contribution_unit_mismatch_is_rejected():
    result = _run(mp.WrongContributionUnitModel())
    assert any("output:unit" in f for f in result.flags)


def test_output_wrong_draw_count_is_rejected():
    result = _run(mp.WrongDrawCountModel())
    assert any("output:shape" in f for f in result.flags)


def test_output_details_schema_violation_is_rejected():
    result = _run(mp.BadDetailsModel())
    assert any("output:details" in f for f in result.flags)


def test_output_valid_model_passes_every_check():
    result = _run(mp.CashModel())
    assert result.execution == "completed"
    assert result.status == "ok"
