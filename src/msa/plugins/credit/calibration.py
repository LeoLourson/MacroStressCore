"""Calibration registries as versioned data files (spec 7.1, 19).

A registry file carries the PD coefficient sets by segment and horizon, the segment mapping
and the section-19 inclusion rule: which review flags a result may carry and still enter
the portfolio, with disclosure.

The demo stand ships one synthetic registry, valid only in the demo namespace. Production
loads the bank's approved file named by ``MSA_CALIBRATION_REGISTRY``; without it every PD
stays a ``risk_score`` and the portfolio carries no money loss.
"""

import json
import os
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

from msa.engine.credit import CalibrationRegistry, PDCalibration
from msa.engine.impact import ThresholdRule

from .track_a import V3ModelRegistry, review_triggers

PACKAGED = Path(__file__).with_name("registries")
DEMO_REGISTRY = "demo-synthetic-2026-09"
NONE = "none"


@dataclass(frozen=True)
class InclusionRule:
    """An approved rule that admits ``needs_review`` results into the portfolio (spec 19)."""

    rule_id: str
    allowed_flags: tuple[str, ...]
    approved_by: str
    approved_on: date
    text: str

    def blocking(self, result) -> list[str]:
        """Review flags of the result that this rule does not cover."""
        return [
            flag
            for flag in review_triggers(result.flags)
            if not any(
                flag == allowed or (allowed.endswith(":") and flag.startswith(allowed))
                for allowed in self.allowed_flags
            )
        ]

    def admits(self, result) -> bool:
        return result.status == "needs_review" and not self.blocking(result)


@dataclass(frozen=True)
class Registry:
    registry_id: str
    kind: str
    note: str
    model: V3ModelRegistry
    inclusion: InclusionRule | None

    def describe(self) -> dict:
        return {
            "registry_id": self.registry_id,
            "kind": self.kind,
            "note": self.note,
            "segments": [segment for segment, _ in self.model.calibrations.segments()],
            "inclusion_rule": None
            if self.inclusion is None
            else {
                "rule_id": self.inclusion.rule_id,
                "text": self.inclusion.text,
                "allowed_flags": list(self.inclusion.allowed_flags),
                "approved_by": self.inclusion.approved_by,
                "approved_on": self.inclusion.approved_on.isoformat(),
            },
        }


def parse(raw: dict) -> Registry:
    approved_on = date.fromisoformat(raw["approved_on"])
    synthetic = raw["kind"] == "synthetic_demo"
    calibrations = []
    for item in raw.get("pd", []):
        # A synthetic set has no sample: its periods collapse to the approval date and its
        # quality metrics say so rather than inventing numbers.
        calibrations.append(
            PDCalibration(
                segment_id=item["segment_id"],
                default_definition=item["default_definition"],
                horizon_months=item["horizon_months"],
                training_period=_period(item.get("training_period"), approved_on),
                validation_period=_period(item.get("validation_period"), approved_on),
                calibrated_on=date.fromisoformat(item.get("calibrated_on", raw["approved_on"])),
                discrimination=item.get("discrimination") or {"not_measured": 0.0},
                calibration_metrics=item.get("calibration_metrics") or {"not_measured": 0.0},
                limitations=item.get("limitations", raw["note"]),
                coefficients=item["coefficients"],
                monotone=item.get("monotone", {}),
                optional_features=item.get("optional_features", {}),
            )
        )
    rule = raw.get("review_inclusion")
    return Registry(
        registry_id=raw["registry_id"],
        kind=raw["kind"],
        note=raw["note"],
        model=V3ModelRegistry(
            calibrations=CalibrationRegistry(calibrations),
            # Banding rules of the risk axes; without them every axis is "not assessed".
            axis_rules=[
                ThresholdRule(
                    rule_id=item["rule_id"],
                    version=item["version"],
                    axis=item["axis"],
                    measure=item["measure"],
                    cutoffs=tuple(item["cutoffs"]),
                    reason=item["reason"],
                    recommendation=item["recommendation"],
                    calibrated=bool(item.get("calibrated", False)),
                )
                for item in raw.get("axis_rules", [])
            ],
            segment_by_okved=raw.get("segment_by_okved", {}),
            segment_by_asset_type=raw.get("segment_by_asset_type", {}),
            market_from_profile=bool(raw.get("market_from_profile", False)),
            synthetic_calibration=synthetic,
            registry_id=raw["registry_id"],
        ),
        inclusion=None
        if rule is None
        else InclusionRule(
            rule_id=rule["rule_id"],
            allowed_flags=tuple(rule["allowed_flags"]),
            approved_by=rule["approved_by"],
            approved_on=date.fromisoformat(rule["approved_on"]),
            text=rule["text"],
        ),
    )


@cache
def load(registry_id: str) -> Registry:
    """A registry by id: ``none``, a packaged file, or the production file."""
    if registry_id == NONE:
        return Registry(NONE, "none", "Калибровка PD не загружена.", V3ModelRegistry(), None)
    production = os.getenv("MSA_CALIBRATION_REGISTRY")
    candidates = [PACKAGED / f"{registry_id}.json"]
    if production:
        candidates.insert(0, Path(production))
    for path in candidates:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw["registry_id"] == registry_id:
                return parse(raw)
    raise KeyError(f"Unknown calibration registry: {registry_id}")


def for_scope(scope: str) -> str:
    """Registry id a namespace calculates with; the synthetic set never reaches production."""
    if scope == "demo":
        return DEMO_REGISTRY
    production = os.getenv("MSA_CALIBRATION_REGISTRY")
    if not production:
        return NONE
    raw = json.loads(Path(production).read_text(encoding="utf-8"))
    if raw["kind"] == "synthetic_demo":
        raise ValueError("A synthetic calibration registry is not allowed in production")
    return raw["registry_id"]


def _period(value, fallback: date) -> tuple[date, date]:
    if not value:
        return (fallback, fallback)
    start, end = value
    return (date.fromisoformat(start), date.fromisoformat(end))
