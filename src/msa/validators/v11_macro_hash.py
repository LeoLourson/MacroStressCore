"""V11 checks all branches, including needs_review results."""

from msa.contracts import CalculationResult

from .base import Verdict


def check(asset_results, expected_hash=None) -> list[Verdict]:
    results = [CalculationResult.model_validate(r) for r in asset_results]
    reference = expected_hash or next((r.macro_draws_sha256 for r in results), None)
    errors = []
    for index, result in enumerate(results):
        if result.macro_draws_sha256 is None or result.macro_draws_sha256 != reference:
            errors.append(
                Verdict(
                    ok=False,
                    rule_id="V11",
                    path=f"/{index}/macro_draws_sha256",
                    message=(
                        f"Position {result.position_id} did not use the run's shared macro matrix"
                    ),
                )
            )
    return errors or [
        Verdict(
            ok=True,
            rule_id="V11",
            path="",
            message="All branches share the macro matrix"
            if results
            else "No position branches to compare",
        )
    ]
