"""The rule table that chooses actions (TZ 3.6), for the rules every plugin declares.

A rule reads one observation of a result — a P50, a breach probability, a share — through
the observation function its plugin declares, which also names the number's path in the
metric tree; the recommendation cites that path, so it traces to the number it fired on
(V9). The thresholds in force are data (``rule_threshold``); a rule absent from them runs
on its declared default, and the report says so.
"""

from msa.contracts import CalculationResult
from msa.contracts.recommendation import Recommendation

OPERATORS = {
    "lt": lambda value, threshold: value < threshold,
    "le": lambda value, threshold: value <= threshold,
    "gt": lambda value, threshold: value > threshold,
    "ge": lambda value, threshold: value >= threshold,
}


def thresholds_in_force(registry, stored: dict | None) -> tuple[dict, list[str]]:
    """``(rule_id -> rule dict, rules on their declared default)``."""
    stored = stored or {}
    rules, defaults = {}, []
    for rule_id, rule in registry.rules.items():
        row = stored.get(rule_id)
        if row is None:
            defaults.append(rule_id)
            row = {
                "metric": rule.observation,
                "operator": rule.operator,
                "threshold": rule.threshold,
                "actions": list(rule.actions),
                "fallback_only": rule.fallback_only,
            }
        rules[rule_id] = row
    return rules, defaults


def apply(result, registry, thresholds: dict, context: dict | None = None) -> list[Recommendation]:
    """The recommendations for one result, rule by rule of its plugin, in declared order."""
    result = CalculationResult.model_validate(result)
    # No action rests on an invalid or uncalculated result.
    if result.execution != "completed" or result.status == "invalid":
        return []
    plugin = registry.plugins.get(result.plugin_id)
    if plugin is None:
        return []
    recommendations, fired = [], False
    for spec in plugin.rules:
        rule = thresholds.get(spec.rule_id)
        if rule is None:
            continue
        if rule.get("fallback_only", spec.fallback_only) and fired:
            continue
        observe = registry.observations.get(rule.get("metric", spec.observation))
        observed = observe(result, context or {}) if observe else None
        if observed is None:
            continue
        value, path = observed
        if not OPERATORS[rule["operator"]](value, rule["threshold"]):
            continue
        if not rule.get("fallback_only", spec.fallback_only):
            fired = True
        for action in rule["actions"]:
            recommendations.append(
                Recommendation(
                    position_id=result.position_id,
                    action=action,
                    rule_id=spec.rule_id,
                    metric_refs=[path],
                )
            )
    return recommendations
