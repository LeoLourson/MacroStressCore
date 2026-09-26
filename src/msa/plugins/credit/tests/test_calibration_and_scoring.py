"""Credit plugin: calibration.load()/for_scope(), and math.credit.score() error paths.

score() is the PD/PD-proxy logistic function shared by the credit models: without a
calibration it falls back to a labelled score; with one, every coefficient it was fitted
on must be provided as a feature (audit finding A1) — a missing or an unknown feature is
an error, never a silent zero.
"""

from datetime import date

import numpy as np
import pytest

from msa.plugins.credit import calibration
from msa.plugins.credit.math.credit import PDCalibration, score
from msa.plugins.credit.wording import FLAGS as CREDIT_FLAGS
from msa.reporting.wording import flag

# -- calibration.load / for_scope -----------------------------------------------------------


def test_load_none_registry_has_no_calibrations_and_no_inclusion_rule():
    reg = calibration.load(calibration.NONE)
    assert reg.kind == "none"
    assert reg.inclusion is None


def test_load_unknown_registry_id_raises_keyerror():
    with pytest.raises(KeyError, match="Unknown calibration registry"):
        calibration.load("no-such-registry-id")


def test_load_demo_registry_is_synthetic_and_has_an_inclusion_rule():
    reg = calibration.load(calibration.DEMO_REGISTRY)
    assert reg.model.calibrations.segments()
    assert reg.inclusion is not None


def test_for_scope_demo_always_returns_the_demo_registry():
    assert calibration.for_scope("demo") == calibration.DEMO_REGISTRY


def test_for_scope_production_without_env_var_returns_none(monkeypatch):
    monkeypatch.delenv("MSA_CALIBRATION_REGISTRY", raising=False)
    assert calibration.for_scope("production") == calibration.NONE


def test_registry_describe_lists_segments_and_inclusion_rule():
    reg = calibration.load(calibration.DEMO_REGISTRY)
    described = reg.describe()
    assert described["registry_id"] == calibration.DEMO_REGISTRY
    assert described["segments"]
    assert described["inclusion_rule"]["rule_id"]


# -- math.credit.score(): calibrated feature requirements ----------------------------------


def pd_calibration(coefficients, *, optional_features=None):
    today = date(2026, 1, 1)
    return PDCalibration(
        segment_id="seg1",
        default_definition="90dpd",
        horizon_months=12,
        training_period=(today, today),
        validation_period=(today, today),
        calibrated_on=today,
        discrimination={"not_measured": 0.0},
        calibration_metrics={"not_measured": 0.0},
        limitations="test",
        coefficients=coefficients,
        optional_features=optional_features or {},
    )


def test_score_without_calibration_falls_back_to_an_uncalibrated_score():
    flags = []
    result = score({"r_icr": np.array([1.0])}, None, flags=flags)
    assert result.calibrated is False
    assert "pd_uncalibrated" in flags


def test_score_with_calibration_and_every_feature_present_is_calibrated():
    calib = pd_calibration({"intercept": -2.0, "r_icr": 1.0})
    result = score({"r_icr": np.array([0.5])}, calib, segment_id="seg1")
    assert result.calibrated is True
    assert result.segment_id == "seg1"


def test_score_rejects_a_feature_the_calibration_has_no_coefficient_for():
    calib = pd_calibration({"intercept": -2.0, "r_icr": 1.0})
    with pytest.raises(ValueError, match="has no coefficient for"):
        score({"r_icr": np.array([0.5]), "unknown_feature": np.array([1.0])}, calib)


def test_score_rejects_a_calibrated_feature_the_model_does_not_provide():
    calib = pd_calibration({"intercept": -2.0, "r_icr": 1.0, "r_lev": 0.5})
    with pytest.raises(ValueError, match="requires features .*r_lev.* the model does not provide"):
        score({"r_icr": np.array([0.5])}, calib)


def test_score_optional_feature_may_be_omitted_without_error():
    calib = pd_calibration(
        {"intercept": -2.0, "r_icr": 1.0, "r_lev": 0.5}, optional_features={"r_lev": 0.0}
    )
    result = score({"r_icr": np.array([0.5])}, calib)
    assert result.calibrated is True


# -- credit wording: nested profile:>/lgd:> markers -------------------------------------------


def test_credit_wording_profile_marker_delegates_to_the_inner_flag():
    result = flag("profile:missing_financials_and_peers", CREDIT_FLAGS)
    assert result == CREDIT_FLAGS["missing_financials_and_peers"]


def test_credit_wording_lgd_marker_delegates_to_the_inner_flag():
    result = flag("lgd:lgd_not_applicable", CREDIT_FLAGS)
    assert result == CREDIT_FLAGS["lgd_not_applicable"]
