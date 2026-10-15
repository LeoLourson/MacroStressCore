"""msa.agents.explain: _numbers_in(), verify() — matching an answer's numbers to tool sources.

Numbers may appear in the answer with a thousands separator, negative, inside a numbered
list, or as a percentage of a fractional source value; verify() must still find them (or
correctly report them as unverified) without mistaking a cited metric path or a list marker
for a number of its own.
"""

from msa.agents.explain import _numbers_in, verify


def source(tool, *values):
    return {"tool": tool, "values": [repr(float(v)) for v in values]}


# -- _numbers_in() --------------------------------------------------------------------------


def test_numbers_in_collects_numeric_fields_and_string_numbers():
    value = {"a": 1.5, "b": "текст с 42 числом", "c": [10, {"d": 3.0}]}
    found = _numbers_in(value)
    assert "1.5" in found
    assert "42" in found
    assert "10.0" in found
    assert "3.0" in found


def test_numbers_in_ignores_booleans_and_none():
    assert _numbers_in({"ok": True, "missing": None}) == []


def test_numbers_in_of_a_plain_string():
    assert _numbers_in("значение 7,5") == ["7.5"]


# -- verify(): thousands separators -----------------------------------------------------


def test_verify_matches_a_thousands_separated_number():
    answer = "Выручка составила 1 234,50 млн руб."
    sources = [source("get_position_metrics", 1234.50)]
    checked, unverified = verify(answer, sources)
    assert unverified == []
    assert checked[0]["source_value"] == 1234.50


# -- verify(): negative numbers -----------------------------------------------------------


def test_verify_matches_a_negative_answer_number_against_a_positive_source_value():
    answer = "Изменение составило -15,00 млн руб."
    sources = [source("get_position_metrics", 15.0)]
    checked, unverified = verify(answer, sources)
    assert unverified == []
    assert checked[0]["text"] == "-15.00"


def test_verify_matches_a_negative_answer_number_against_a_negative_source_value():
    answer = "Изменение составило -15,00 млн руб."
    sources = [source("get_position_metrics", -15.0)]
    checked, unverified = verify(answer, sources)
    assert unverified == []


# -- verify(): list markers are not numbers of their own -----------------------------------


def test_verify_strips_numbered_list_markers_before_scanning():
    answer = "1. Первое значение: 10,00.\n2. Второе значение: 20,00."
    sources = [source("t", 10.0, 20.0)]
    checked, unverified = verify(answer, sources)
    assert unverified == []
    assert {c["text"] for c in checked} == {"10.00", "20.00"}


def test_verify_list_marker_with_parenthesis_is_also_stripped():
    answer = "1) Значение: 5,00."
    sources = [source("t", 5.0)]
    _, unverified = verify(answer, sources)
    assert unverified == []


# -- verify(): percentage scaling of a fractional source value -------------------------------


def test_verify_matches_a_percentage_of_a_fractional_source_value():
    answer = "Доля покрытия — 15,00 %."
    sources = [source("get_run_summary", 0.15)]
    checked, unverified = verify(answer, sources)
    assert unverified == []
    assert checked[0]["scaled"] is True
    assert checked[0]["source_value"] == 0.15


# -- verify(): metric paths are removed, not read as numbers ---------------------------------


def test_verify_strips_cited_metric_paths_so_position_numbers_in_them_are_not_counted():
    answer = "Значение метрики [/positions/POS1/metrics/equity.pnl/p50] равно 7,00."
    sources = [source("t", 7.0)]
    checked, unverified = verify(answer, sources)
    assert unverified == []
    assert checked == [{"text": "7.00", "tool": "t", "source_value": 7.0, "scaled": False}]


# -- verify(): unverified numbers are reported once each --------------------------------------


def test_verify_reports_an_unmatched_number_as_unverified():
    answer = "Итог — 999,99."
    sources = [source("t", 1.0)]
    checked, unverified = verify(answer, sources)
    assert checked == []
    assert unverified == ["999.99"]


def test_verify_deduplicates_repeated_unverified_numbers():
    answer = "Итог 42,00, ещё раз 42,00."
    sources = [source("t", 1.0)]
    _, unverified = verify(answer, sources)
    assert unverified == ["42.00"]


def test_verify_with_no_numbers_in_the_answer_is_fully_verified():
    checked, unverified = verify("Позиция рассчитана без ограничений.", [source("t", 1.0)])
    assert checked == []
    assert unverified == []
