"""msa.reporting.context: ReportContext.cite/interval/position/channel/flag, display_id, join."""

from datetime import date

from msa.platform.registry import build
from msa.reporting.context import ReportContext, display_id, join, plain
from tests import minimal_plugin as mp


def registry():
    return build([mp.plugin, mp.MARKET_PLUGIN])


def ctx(tree, **overrides):
    values = {
        "tree": tree,
        "results": [],
        "portfolio": None,
        "registry": registry(),
    }
    values.update(overrides)
    return ReportContext(**values)


# -- display_id / plain / join -----------------------------------------------------------


def test_display_id_prefixes_hash_when_value_starts_with_digit():
    assert display_id("123") == "#123"
    assert display_id("-5") == "#-5"
    assert display_id("POS1") == "POS1"


def test_plain_is_false_for_text_containing_a_number():
    assert plain("Позиция 1") is False
    assert plain("Позиция") is True
    assert plain(None) is False
    assert plain("") is False


def test_join_formats_list_with_and_for_last_item():
    assert join(["a"]) == "a"
    assert join(["a", "b"]) == "a и b"
    assert join(["a", "b", "c"]) == "a, b и c"


# -- ReportContext.cite / interval --------------------------------------------------------


def test_cite_returns_rounded_value_with_comma_and_records_number_ref():
    context = ctx({"m": {"value": 1.567}})
    text = context.cite("/m/value", places=2)
    assert text == "1,57"
    assert len(context.numbers) == 1
    assert context.numbers[0].metric_path == "/m/value"
    assert context.numbers[0].rounding == 2


def test_interval_collapses_when_p05_and_p95_round_equal():
    context = ctx({"m": {"p05": 1.001, "p50": 1.002, "p95": 1.003}})
    text = context.interval("/m", "млн руб.", places=2)
    assert text == "1,00 млн руб. во всех сценариях"


def test_interval_shows_the_full_range_when_bounds_differ():
    context = ctx({"m": {"p05": 1.0, "p50": 2.0, "p95": 3.0}})
    text = context.interval("/m", "млн руб.", places=2)
    assert text == "2,00 млн руб. по медиане (P50), P5–P95 — от 1,00 до 3,00 млн руб."


# -- position / channel -------------------------------------------------------------------


def test_position_uses_name_and_id_when_name_is_plain_text():
    context = ctx({}, names={"POS1": "ООО Ромашка"})
    assert context.position("POS1") == "ООО Ромашка (POS1)"


def test_position_falls_back_to_display_id_when_name_missing():
    context = ctx({})
    assert context.position("POS1") == "POS1"


def test_position_falls_back_to_display_id_when_name_contains_a_number():
    context = ctx({}, names={"POS1": "Позиция 1"})
    assert context.position("POS1") == "POS1"


def test_channel_wraps_plain_label_in_guillemets():
    context = ctx({}, channels={"c1": "спрос"})
    assert context.channel("c1") == "«спрос»"


def test_channel_falls_back_to_display_id_without_a_label():
    context = ctx({})
    assert context.channel("c1") == "c1"


# -- status / of_types / label -------------------------------------------------------------


def test_status_maps_known_status_words():
    context = ctx({})
    assert context.status("ok") != "ok"


def test_status_falls_back_to_the_raw_value_for_unknown_status():
    context = ctx({})
    assert context.status("mystery_status") == "mystery_status"


def test_of_types_filters_by_instrument_type():
    reg = registry()
    instrument = _minimal_result("A", "minimal_cash")
    other = _minimal_result("B", "other_type")
    context = ctx({}, results=[instrument, other], registry=reg)
    assert [r.position_id for r in context.of_types({"minimal_cash"})] == ["A"]


def test_of_types_with_empty_set_returns_everything():
    reg = registry()
    instrument = _minimal_result("A", "minimal_cash")
    context = ctx({}, results=[instrument], registry=reg)
    assert context.of_types(()) == [instrument]


def test_label_reads_the_registered_metric_label():
    reg = registry()
    context = ctx({}, registry=reg)
    assert context.label(mp.VALUE_METRIC) == "Value"


def test_label_falls_back_to_the_metric_id_when_unregistered():
    reg = registry()
    context = ctx({}, registry=reg)
    assert context.label("no.such.metric") == "no.such.metric"


def _minimal_result(position_id, instrument_type):
    from msa.contracts.result import CalculationResult

    return CalculationResult(
        position_id=position_id,
        instrument_id=position_id,
        instrument_type=instrument_type,
        plugin_id="minimal",
        plugin_version="1.0.0",
        model_id="m",
        model_version="1.0.0",
        as_of=date(2026, 1, 1),
        horizon=12,
        seed=1,
        execution="completed",
        status="ok",
        scenario_id="a" * 64,
    )
