"""msa.plugin_sdk.version: parsing and the SDK compatibility clause language."""

import pytest

from msa.plugin_sdk.version import SDK_VERSION, compatible, parse


def test_parse_full_version():
    assert parse("1.2.3") == (1, 2, 3)


def test_parse_defaults_missing_patch_to_zero():
    assert parse("1.2") == (1, 2, 0)


def test_parse_rejects_bad_version_string():
    with pytest.raises(ValueError, match="not a version"):
        parse("not-a-version")


def test_parse_rejects_version_with_too_many_parts():
    with pytest.raises(ValueError, match="not a version"):
        parse("1.2.3.4")


@pytest.mark.parametrize(
    ("spec", "version", "expected"),
    [
        (">=1.0", "1.0.0", True),
        (">=1.0", "0.9.9", False),
        ("<=1.0", "1.0.0", True),
        ("<=1.0", "1.0.1", False),
        ("==1.0.0", "1.0.0", True),
        ("==1.0.0", "1.0.1", False),
        ("<2.0", "1.9.9", True),
        ("<2.0", "2.0.0", False),
        (">1.0", "1.0.1", True),
        (">1.0", "1.0.0", False),
    ],
)
def test_compatible_supports_every_operator(spec, version, expected):
    assert compatible(spec, version) is expected


def test_compatible_defaults_to_current_sdk_version():
    assert compatible(">=1.0,<2.0")
    assert compatible(">=1.0,<2.0", SDK_VERSION)


def test_compatible_requires_every_comma_separated_clause():
    assert compatible(">=1.0,<2.0", "1.5.0")
    assert not compatible(">=1.0,<2.0", "2.0.0")
    assert not compatible(">=1.0,<2.0", "0.9.0")


def test_compatible_rejects_empty_range():
    with pytest.raises(ValueError, match="empty compatibility range"):
        compatible("", "1.0.0")


def test_compatible_rejects_blank_range_of_only_commas():
    with pytest.raises(ValueError, match="empty compatibility range"):
        compatible(" , , ", "1.0.0")


def test_compatible_rejects_malformed_clause():
    with pytest.raises(ValueError, match="not a version clause"):
        compatible("~1.0", "1.0.0")


def test_compatible_rejects_clause_with_bad_bound_version():
    with pytest.raises(ValueError, match="not a version clause"):
        compatible(">=abc", "1.0.0")
