"""The credit plugin's own conformance case: shipped with the plugin, not with the stand.

A corporate loan and a bond with their borrowers' statements, the risk-free rate and a
two-channel scenario on a graph that reaches both sectors.
"""

import json
from functools import cache
from pathlib import Path

from msa.plugin_sdk import DataSnapshot, DemoCase, PortfolioBundle

CASE = Path(__file__).with_name("demo_case.json")


@cache
def _raw() -> dict:
    return json.loads(CASE.read_text(encoding="utf-8"))


def cases() -> list[DemoCase]:
    raw = _raw()
    return [
        DemoCase(
            name="credit.corporate_and_bond",
            bundle=PortfolioBundle.model_validate(raw["bundle"]),
            snapshot=DataSnapshot.model_validate(raw["snapshot"]),
            scenario=raw["scenario"],
            graph=raw["graph"],
            completes=tuple(raw["completes"]),
        )
    ]
