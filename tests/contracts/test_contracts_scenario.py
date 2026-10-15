"""msa.contracts.scenario: MacroParameter distribution validation and central_value()."""

import pytest
from pydantic import ValidationError

from msa.contracts.scenario import MacroParameter, central_value


def test_point_requires_value():
    with pytest.raises(ValidationError, match="point requires value"):
        MacroParameter(kind="point", unit="fraction")


def test_point_central_value_is_value():
    p = MacroParameter(kind="point", value=0.5, unit="fraction")
    assert central_value(p) == 0.5


def test_triangular_requires_low_mode_high():
    with pytest.raises(ValidationError, match="triangular requires low, mode and high"):
        MacroParameter(kind="triangular", low=0.0, mode=0.5, unit="fraction")


def test_triangular_requires_ordered_bounds():
    with pytest.raises(ValidationError, match="low <= mode <= high"):
        MacroParameter(kind="triangular", low=0.5, mode=0.1, high=1.0, unit="fraction")


def test_triangular_rejects_low_equal_high():
    with pytest.raises(ValidationError, match="low <= mode <= high"):
        MacroParameter(kind="triangular", low=0.5, mode=0.5, high=0.5, unit="fraction")


def test_triangular_central_value_is_mode():
    p = MacroParameter(kind="triangular", low=0.0, mode=0.3, high=1.0, unit="fraction")
    assert central_value(p) == 0.3


def test_uniform_requires_low_and_high():
    with pytest.raises(ValidationError, match="uniform requires low and high"):
        MacroParameter(kind="uniform", low=0.0, unit="fraction")


def test_uniform_requires_low_less_than_high():
    with pytest.raises(ValidationError, match="low < high"):
        MacroParameter(kind="uniform", low=1.0, high=1.0, unit="fraction")


def test_uniform_central_value_is_midpoint():
    p = MacroParameter(kind="uniform", low=0.0, high=2.0, unit="fraction")
    assert central_value(p) == 1.0


def test_truncated_normal_requires_all_fields():
    with pytest.raises(ValidationError, match="truncated_normal requires"):
        MacroParameter(kind="truncated_normal", mean=0.0, sigma=1.0, unit="fraction")


def test_truncated_normal_requires_positive_sigma():
    with pytest.raises(ValidationError, match="sigma > 0"):
        MacroParameter(
            kind="truncated_normal", mean=0.0, sigma=0.0, low=-1.0, high=1.0, unit="fraction"
        )


def test_truncated_normal_requires_low_less_than_high():
    with pytest.raises(ValidationError, match="low < high"):
        MacroParameter(
            kind="truncated_normal", mean=0.0, sigma=1.0, low=1.0, high=1.0, unit="fraction"
        )


def test_truncated_normal_central_value_is_mean():
    p = MacroParameter(
        kind="truncated_normal", mean=0.25, sigma=1.0, low=-1.0, high=1.0, unit="fraction"
    )
    assert central_value(p) == 0.25


def test_extra_fields_are_forbidden():
    with pytest.raises(ValidationError):
        MacroParameter(kind="point", value=1.0, unit="fraction", surprise=True)


def test_factor_channel_and_key_are_optional_metadata():
    p = MacroParameter(
        kind="point",
        value=1.0,
        unit="fraction",
        factor="credit.revenue",
        channel="channel",
    )
    assert p.factor == "credit.revenue"
    assert p.key is None
