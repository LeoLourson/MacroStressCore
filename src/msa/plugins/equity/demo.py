"""The equity plugin's own conformance case: a rouble and a dollar share with their data."""

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
            name="equity.rouble_and_dollar_shares",
            bundle=PortfolioBundle.model_validate(raw["bundle"]),
            snapshot=DataSnapshot.model_validate(raw["snapshot"]),
            scenario=raw["scenario"],
            graph=raw["graph"],
            completes=tuple(raw["completes"]),
        )
    ]
