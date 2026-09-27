"""Credit plugin: coverage_feature() and raw_icr() at an infinite (no-interest) ICR.

A borrower without interest (no debt, or a covenant period funded entirely by cash) has
nothing to cover: the raw ratio is ``+inf``, still undefined as a ratio to disclose, but the
PD feature must read it as the best coverage (0), not as the missing-data cap (A16).
"""

import numpy as np
import pytest

from msa.plugins.credit.math.credit import DEFAULT_ICR_CAP, coverage_feature
from msa.plugins.credit.math.metrics import raw_icr

# -- coverage_feature() -------------------------------------------------------------------


def test_coverage_feature_of_an_infinite_ratio_is_the_best_value_zero():
    result = coverage_feature(np.array([np.inf]), np.array([True]))
    assert result[0] == 0.0


def test_coverage_feature_of_a_finite_ratio_is_log1p_of_its_inverse():
    result = coverage_feature(np.array([2.0]), np.array([True]))
    assert result[0] == pytest.approx(np.log1p(0.5))


def test_coverage_feature_undefined_is_capped():
    result = coverage_feature(np.array([1.0]), np.array([False]))
    assert result[0] == DEFAULT_ICR_CAP


# -- raw_icr() -----------------------------------------------------------------------------


def test_raw_icr_no_interest_and_positive_ebitda_is_infinite_and_undefined():
    result = raw_icr(np.array([100.0]), np.array([0.0]))
    assert result.value[0] == np.inf
    assert not result.defined[0]
    assert np.isnan(result.masked()[0])


def test_raw_icr_no_interest_and_nonpositive_ebitda_is_nan_and_undefined():
    result = raw_icr(np.array([-10.0]), np.array([0.0]))
    assert np.isnan(result.value[0])
    assert not result.defined[0]


def test_raw_icr_positive_interest_is_the_plain_ratio_and_defined():
    result = raw_icr(np.array([200.0]), np.array([50.0]))
    assert result.value[0] == pytest.approx(4.0)
    assert result.defined[0]
