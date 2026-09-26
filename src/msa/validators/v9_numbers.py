from msa.contracts.report import Report
from msa.reporting.numbers import check_refs, extract_numbers

from .base import Verdict


class NumbersValidator:
    def __init__(self, metric_tree=None):
        self.metric_tree = metric_tree

    def check(self, payload, metrics=None):
        report = Report.model_validate(payload)
        tree = metrics if metrics is not None else self.metric_tree
        if tree is None:
            if report.numbers or extract_numbers(report.summary):
                return [
                    Verdict(
                        ok=False,
                        rule_id="V9",
                        path="/numbers",
                        message="Quantitative metric tree is required for V9",
                    )
                ]
            return [
                Verdict(
                    ok=True, rule_id="V9", path="/summary", message="Report contains no numbers"
                )
            ]
        errors = check_refs(report.summary, report.numbers, tree)
        return [Verdict(ok=False, rule_id="V9", path="/summary", message=e) for e in errors] or [
            Verdict(
                ok=True,
                rule_id="V9",
                path="/summary",
                message="All report numbers trace to metrics",
            )
        ]
