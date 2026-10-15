"""Risk Advisory (TZ 3.6): actions by the rule tables, text traced to metrics.

The report is assembled from the results by the common skeleton and the sections the
plugins declare, and every number in it is a citation. The LLM may rewrite the summary;
V9 accepts its text only when every number in it traces to the same metric tree,
otherwise the template text stays.
"""

from pydantic import ValidationError

from msa.contracts import Report
from msa.prompts.registry import messages_for
from msa.reporting.builder import build
from msa.reporting.tree import metric_tree
from msa.validators.v9_numbers import NumbersValidator

from msa.contracts.advisory import AdvisoryNarrative
from .base import AgentFailure
from msa.contracts.causal_answer import ScenarioParameter


def channel_factors(parameters) -> dict[str, str]:
    """Scenario channel -> the factor its parameters move; rules read rate and FX channels."""
    factors = {}
    for name, raw in (parameters or {}).items():
        parameter = ScenarioParameter.model_validate({"label": name, **raw})
        if parameter.channel and parameter.factor:
            factors[parameter.channel] = parameter.factor
    return factors


def plugin_notes(registry, options) -> dict:
    return {
        plugin_id: plugin.notes(options)
        for plugin_id, plugin in registry.plugins.items()
        if plugin.notes is not None
    }


class AdvisoryAgent:
    def __init__(self, *, registry, thresholds_repository=None, llm=None, options=None):
        self.registry = registry
        self.thresholds_repository = thresholds_repository
        self.llm = llm
        self.options = options or {}

    def run(self, payload: dict) -> Report:
        thresholds = payload.get("thresholds")
        if thresholds is None:
            if self.thresholds_repository is None:
                raise ValueError("Advisory needs seeded rule thresholds or a repository")
            thresholds = self.thresholds_repository.current()
        parameters = payload.get("macro_parameters") or {}
        factors = channel_factors(parameters)
        parsed = {
            name: ScenarioParameter.model_validate({"label": name, **raw})
            for name, raw in parameters.items()
        }
        report = build(
            payload.get("results", []),
            payload.get("portfolio"),
            payload.get("positions", []),
            run_id=payload["run_id"],
            graph=payload.get("graph"),
            thresholds=thresholds,
            registry=self.registry,
            mode=payload.get("mode", "production"),
            names=payload.get("position_names"),
            scenario_evidence=[e for p in parsed.values() for e in p.evidence],
            channel_factors=factors,
            shock_labels={name: p.label for name, p in parsed.items()},
            notes=plugin_notes(self.registry, payload.get("options") or self.options),
        )
        tree = metric_tree(
            report.results,
            report.portfolio,
            registry=self.registry,
            context={"channel_factors": factors},
        )
        validator = NumbersValidator()
        if self.llm is not None:
            errors = []
            for _ in range(3):
                messages = messages_for("advisory", report.summary, violations=errors)
                try:
                    draft = self.llm.complete(messages, AdvisoryNarrative, payload["seed"])
                except (ValidationError, ValueError, KeyError, OSError) as exc:
                    errors = [str(exc)]
                    continue
                candidate = report.model_copy(update={"summary": draft.summary})
                verdicts = validator.check(candidate, tree)
                if all(v.ok for v in verdicts):
                    return candidate
                errors = [v.message for v in verdicts if not v.ok]
            # V9 failures fall back to the deterministic report template.
        verdicts = validator.check(report, tree)
        if any(not verdict.ok for verdict in verdicts):
            raise AgentFailure([v.message for v in verdicts if not v.ok])
        return report
