"""The credit models reproduce their reference results on the demo portfolios.

``credit_reference.json`` holds the inputs and the results written by
``capture_reference.py``: every credit position of MULTI-ASSET and ATYPICAL-BORROWERS on a
scenario that moves five drivers through a graph with lags and a triangular elasticity, and
each portfolio's credit-loss slice. The test runs the same inputs through the platform (the
dispatcher, the credit plugin and the slice aggregator) and compares.

The realisations are compared through a summary of each parameter's draws, not through
their hash: the last digits of floating-point arithmetic may differ between platforms, and
the tolerance covers that.
"""

import json

import pytest

from .capture_reference import REFERENCE, draw_summaries, run

GOLDEN = json.loads(REFERENCE.read_text("utf-8"))
SETTINGS = {key: GOLDEN[key] for key in ("as_of", "seed", "points", "replicates", "horizon")}
#: Relative, above a scale of one. The drift between Windows and Linux seen so far is 2e-9.
TOLERANCE = 1e-8
#: Hashes of the code and of the realisations; the numbers they stand for are compared.
NOT_COMPARED = ("code_sha256", "macro_draws_sha256")


def differences(expected, actual, path=""):
    if path.endswith(NOT_COMPARED):
        return []
    if isinstance(expected, dict) and isinstance(actual, dict):
        found = []
        for key in sorted(set(expected) | set(actual)):
            if key not in expected or key not in actual:
                found.append(f"{path}/{key}: present on one side only")
            else:
                found += differences(expected[key], actual[key], f"{path}/{key}")
        return found
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [f"{path}: {len(expected)} items, got {len(actual)}"]
        return [
            d
            for i, (a, b) in enumerate(zip(expected, actual, strict=False))
            for d in differences(a, b, f"{path}/{i}")
        ]
    if isinstance(expected, float | int) and isinstance(actual, float | int):
        if isinstance(expected, bool) or isinstance(actual, bool):
            return [] if expected == actual else [f"{path}: {expected!r} != {actual!r}"]
        scale = max(1.0, abs(expected), abs(actual))
        return (
            []
            if abs(expected - actual) <= TOLERANCE * scale
            else [f"{path}: {expected} != {actual}"]
        )
    return [] if expected == actual else [f"{path}: {expected!r} != {actual!r}"]


@pytest.fixture(scope="module")
def runs():
    return {
        portfolio_id: run(portfolio_id, captured["graph"], GOLDEN["scenario"], SETTINGS)
        for portfolio_id, captured in GOLDEN["portfolios"].items()
    }


def test_the_scenario_draws_match_their_reference():
    assert differences(GOLDEN["draws"], draw_summaries(GOLDEN["scenario"], SETTINGS)) == []


@pytest.mark.parametrize("portfolio_id", sorted(GOLDEN["portfolios"]))
def test_every_position_matches_its_reference(runs, portfolio_id):
    batch, _ = runs[portfolio_id]
    expected = GOLDEN["portfolios"][portfolio_id]["positions"]
    assert sorted(r.position_id for r in batch.results) == sorted(expected)
    for result in batch.results:
        reference = expected[result.position_id]
        assert (result.execution, result.status) == (reference["execution"], reference["status"])
        assert differences(reference["details"], result.details) == [], result.position_id


@pytest.mark.parametrize("portfolio_id", sorted(GOLDEN["portfolios"]))
def test_the_credit_slice_matches_its_reference(runs, portfolio_id):
    _, credit = runs[portfolio_id]
    expected = GOLDEN["portfolios"][portfolio_id]["slice"]
    assert differences(expected, credit.model_dump(mode="json")) == []
