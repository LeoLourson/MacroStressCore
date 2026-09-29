"""The catalog's flag roles and the result views the positions tab groups by."""

import pytest

from msa.platform.catalog import asset_types
from msa.platform.registry import registry


@pytest.fixture(scope="module")
def catalog():
    return asset_types(registry())


def view_of(catalog, type_id):
    return next(t["view"] for t in catalog["types"] if t["asset_type"] == type_id)


@pytest.mark.parametrize("key", ["review_flags", "informational_flags"])
def test_flag_roles_are_sorted_codes(catalog, key):
    codes = catalog[key]
    assert codes and all(isinstance(code, str) for code in codes)
    assert codes == sorted(codes)


def test_review_flags_name_why_a_result_went_to_review(catalog):
    review = set(catalog["review_flags"])
    assert "calibration_synthetic" in review
    # A code ending in ":" covers every flag with that prefix.
    assert {
        "covenant_outside_horizon:",
        "covenant_metric_unavailable:",
        "covenant_metric_undefined:",
        "profile:",
    } <= review


def test_informational_flags_come_from_every_plugin(catalog):
    assert {"factor_not_in_scenario:", "dividends_at_horizon_fx"} <= set(
        catalog["informational_flags"]
    )


@pytest.mark.parametrize("type_id", ["corp_loan", "pf_escrow", "leasing"])
def test_loans_share_the_credit_view(catalog, type_id):
    view = view_of(catalog, type_id)
    assert (view["view_id"], view["component"]) == ("credit.position", "credit.position")


@pytest.mark.parametrize("type_id", ["bond_fixed", "bond_floater"])
def test_bonds_lead_with_the_change_of_their_value(catalog, type_id):
    view = view_of(catalog, type_id)
    loans = view_of(catalog, "corp_loan")
    assert (view["view_id"], view["component"]) == ("credit.bond", "credit.position")
    assert view["summary_metrics"] == ["credit.position_price_change", *loans["summary_metrics"]]
    assert (view["labels"], view["blocks"]) == (loans["labels"], loans["blocks"])


def test_series_keep_the_family_order_and_the_first_label():
    from msa.plugins.credit import series_labels

    labels = series_labels()
    assert list(labels)[:4] == ["revenue", "variable_cost", "opex", "ebitda"]
    assert labels["cash"] == "Денежные средства"


def test_equity_shows_one_summary_metric_and_marks_the_loss_quantiles(catalog):
    view = view_of(catalog, "common_stock")
    assert view["summary_metrics"] == ["equity.pnl"]
    histogram = next(b for b in view["blocks"] if b["kind"] == "histogram")
    assert histogram["metric_ids"] == ["equity.loss"]
