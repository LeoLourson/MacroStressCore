"""msa.reporting.wording: flag() phrasing and informational()."""

from msa.reporting.wording import PLATFORM_FLAGS, flag, informational


def test_flag_exact_match_from_platform_flags():
    assert flag("exposure_unknown", {}) == PLATFORM_FLAGS["exposure_unknown"]


def test_flag_exact_match_from_plugin_wording_overrides_nothing_platform_doesnt_have():
    assert flag("credit.foo", {"credit.foo": "Кастомный флаг"}) == "Кастомный флаг"


def test_flag_prefix_with_argument_substitutes_the_rest():
    result = flag("data_missing:fx", {})
    assert result == "нет данных «fx» на дату оценки"


def test_flag_prefix_without_braces_ignores_the_argument():
    wording = {"plain:": "Постоянная фраза"}
    assert flag("plain:whatever", wording) == "Постоянная фраза"


def test_flag_labels_substitute_the_readable_name():
    labels = {"fx": "курс USD/RUB"}
    result = flag("data_missing:fx", {}, labels)
    assert result == "нет данных «курс USD/RUB» на дату оценки"


def test_flag_argument_with_digits_is_dropped():
    result = flag("data_missing:123", {})
    assert result == "нет данных на дату оценки"
    assert "123" not in result


def test_flag_nested_name_colon_gt_delegates_to_the_rest():
    wording = {"outer:>": "irrelevant marker text", "inner": "Внутренний флаг"}
    assert flag("outer:inner", wording) == "Внутренний флаг"


def test_flag_nested_chain_of_two_levels():
    wording = {"a:>": "x", "b:>": "y", "c": "C"}
    assert flag("a:b:c", wording) == "C"


def test_flag_unknown_without_colon_and_without_digits_returns_code_unchanged():
    assert flag("totally_unknown_flag", {}) == "totally_unknown_flag"


def test_flag_unknown_prefixed_with_digits_drops_the_argument():
    assert flag("custom:42", {}) == "custom"


def test_flag_unknown_prefixed_without_digits_returns_code_unchanged():
    assert flag("custom:abc", {}) == "custom:abc"


# -- informational() ------------------------------------------------------------------------


def test_informational_true_for_exact_flag_match():
    assert informational(
        "factor_not_in_scenario:USD/RUB", frozenset({"factor_not_in_scenario:USD/RUB"})
    )


def test_informational_true_for_prefix_with_colon_match():
    assert informational("factor_not_in_scenario:USD/RUB", frozenset({"factor_not_in_scenario:"}))


def test_informational_true_for_bare_prefix_match():
    assert informational("factor_not_in_scenario:USD/RUB", frozenset({"factor_not_in_scenario"}))


def test_informational_false_when_nothing_matches():
    assert not informational("factor_not_in_scenario:USD/RUB", frozenset({"something_else"}))
