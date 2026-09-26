"""msa.reporting.numbers: JSON-pointer resolution, rounding, number extraction, check_refs."""

from decimal import Decimal

import pytest

from msa.reporting.numbers import (
    check_refs,
    extract_numbers,
    pointer_token,
    resolve_pointer,
    rounded,
)

# -- resolve_pointer / pointer_token -----------------------------------------------------


def test_resolve_pointer_walks_nested_dicts():
    data = {"a": {"b": {"c": 5}}}
    assert resolve_pointer(data, "/a/b/c") == 5


def test_resolve_pointer_requires_leading_slash():
    with pytest.raises(KeyError):
        resolve_pointer({"a": 1}, "a")


def test_resolve_pointer_unescapes_tilde_and_slash_tokens():
    data = {"POS/1": {"a~b": 7}}
    token = pointer_token("POS/1")
    inner = pointer_token("a~b")
    assert resolve_pointer(data, f"/{token}/{inner}") == 7
    assert resolve_pointer(data, "/POS~11/a~0b") == 7


def test_pointer_token_escapes_tilde_before_slash():
    assert pointer_token("a~/b") == "a~0~1b"


def test_resolve_pointer_missing_key_raises_keyerror():
    with pytest.raises(KeyError):
        resolve_pointer({"a": 1}, "/b")


# -- rounded --------------------------------------------------------------------------------


def test_rounded_uses_banker_rounding():
    assert rounded(2.5, 0) == 2
    assert rounded(3.5, 0) == 4


def test_rounded_respects_places():
    assert rounded(1.005, 2) in (Decimal("1.00"), Decimal("1.01"))
    assert rounded(1.25, 1) == Decimal("1.2")


# -- extract_numbers --------------------------------------------------------------------------


def test_extract_numbers_finds_plain_and_decimal_comma_numbers():
    numbers = extract_numbers("Значение 12,5 и ещё 3.0 рубля")
    values = [(float(v), p) for v, p in numbers]
    assert (12.5, 1) in values
    assert (3.0, 1) in values


def test_extract_numbers_ignores_hashed_or_numbered_ids():
    numbers = extract_numbers("Позиция #12 и №5 без изменений")
    assert numbers == []


def test_extract_numbers_integer_has_zero_decimal_places():
    numbers = extract_numbers("Всего 42 позиции")
    assert numbers == [(42, 0)]


# -- check_refs -----------------------------------------------------------------------------


def tree():
    return {"positions": {"POS1": {"metrics": {"m": {"unit": "fraction", "value": 1.5}}}}}


def ref(**overrides):
    values = {"value": 1.5, "metric_path": "/positions/POS1/metrics/m/value", "rounding": 2}
    values.update(overrides)
    return values


def test_check_refs_accepts_a_matching_reference_and_traceable_number():
    errors = check_refs("Значение 1,50.", [ref()], tree())
    assert errors == []


def test_check_refs_reports_missing_metric_path():
    errors = check_refs("текст", [ref(metric_path="/nowhere")], tree())
    assert any("Missing metric" in e for e in errors)


def test_check_refs_reports_non_numeric_metric():
    bad_tree = {"positions": {"POS1": {"metrics": {"m": {"unit": "fraction"}}}}}
    errors = check_refs("текст", [ref(metric_path="/positions/POS1/metrics/m")], bad_tree)
    assert any("not numeric" in e for e in errors)


def test_check_refs_reports_number_differing_from_metric():
    errors = check_refs("текст", [ref(value=9.99)], tree())
    assert any("differs from metric" in e for e in errors)


def test_check_refs_reports_untraceable_number_in_summary():
    errors = check_refs("Итог 7,77 рублей.", [ref()], tree())
    assert any("Untraceable number" in e for e in errors)
