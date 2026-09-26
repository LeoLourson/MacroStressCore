from msa.contracts import CONTRACT_MODELS

from .base import Validator, Verdict
from .v1_contract import check

_VALIDATORS: dict[str, tuple[Validator, frozenset[str]]] = {}


def register(rule_id: str, validator: Validator, applies_to: list[str]) -> None:
    if rule_id not in {f"V{i}" for i in range(2, 12)}:
        raise ValueError("V1 is built in; extension rules must be V2..V11")
    if rule_id in _VALIDATORS:
        raise ValueError(f"Validator already registered: {rule_id}")
    if not applies_to or any(name.removesuffix("[]") not in CONTRACT_MODELS for name in applies_to):
        raise ValueError("applies_to must name known contracts")
    _VALIDATORS[rule_id] = (validator, frozenset(applies_to))


def validate(artifact_type: str, payload) -> list[Verdict]:
    model = CONTRACT_MODELS.get(artifact_type.removesuffix("[]"))
    if model is None:
        return [
            Verdict(
                ok=False,
                rule_id="V1",
                path="/artifact_type",
                message=f"Unknown contract: {artifact_type}",
            )
        ]
    verdicts = check(payload, list[model] if artifact_type.endswith("[]") else model)
    if any(not verdict.ok for verdict in verdicts):
        if artifact_type == "TransmissionGraph":
            # Edge sources and cycles are useful findings even when V1 rejects the graph.
            for rule_id in ("V7", "V8"):
                validator, _ = _VALIDATORS[rule_id]
                verdicts.extend(v for v in validator.check(payload) if not v.ok)
        return verdicts  # Domain validators may rely on structurally valid input.
    for rule_id in sorted(_VALIDATORS, key=lambda rule: int(rule[1:])):
        validator, applies_to = _VALIDATORS[rule_id]
        if artifact_type in applies_to:
            results = validator.check(payload)
            if any(result.rule_id != rule_id for result in results):
                raise ValueError(f"Validator registered as {rule_id} returned another rule ID")
            verdicts.extend(results)
    return verdicts
