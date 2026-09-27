"""Exposure (TZ 3.3): the positions the approved scenario reaches, with their data prepared.

For each position of the portfolio the agent asks its model what it is sensitive to and
what it needs (``requirements``). A position the scenario reaches gets its data resolved
against the run's snapshot — through ``mcp-portfolio`` in a run, so each read is an audited
tool call — and its model's verdict on them (``validate``). A position the scenario does not
reach is not calculated, but its exposure is measured the same way: the portfolio's
concentration and the share the event reached describe the whole portfolio. What an asset
family counts as data quality, and what it does without data, is its plugin's business.
"""

from datetime import date

from msa.contracts.domain import PositionContext
from msa.contracts.graph import TransmissionGraph
from msa.contracts.result import Diagnostic
from msa.contracts.scenario import MacroParameter
from msa.engine import exposure
from msa.engine.dispatch import schema_problems, with_required_data
from msa.engine.snapshot import SnapshotIndex, resolve
from msa.platform.registry import UnknownInstrumentType, UnknownModel
from msa.plugin_sdk.model import Diagnostics, PreparedInputs, RunOptions


class LocalResolver:
    """Resolution against a snapshot held in memory: tests and the demo run."""

    def __init__(self, snapshot, sector_of):
        self.index = SnapshotIndex(snapshot.snapshot_id, snapshot.items)
        self.sector_of = sector_of

    def resolve(self, context, requirements, *, as_of, snapshot_id):
        if snapshot_id != self.index.snapshot_id:
            raise ValueError(f"snapshot {snapshot_id} is not the one loaded")
        return resolve(requirements, self.index, as_of=as_of, sector_of=self.sector_of)


class ExposureAgent:
    def __init__(self, *, registry, resolver=None):
        self.registry, self.resolver = registry, resolver

    def run(self, payload: dict) -> dict:
        graph = payload.get("graph")
        graph = TransmissionGraph.model_validate(graph) if graph else None
        parameters = {
            name: MacroParameter.model_validate(
                {k: v for k, v in value.items() if k in MacroParameter.model_fields}
            )
            for name, value in (payload.get("macro_parameters") or {}).items()
        }
        as_of = payload["as_of"]
        as_of = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
        options = RunOptions(
            as_of=as_of,
            horizon=payload["horizon"],
            base_currency=payload.get("base_currency", "RUB"),
            options=payload.get("options") or {},
        )
        reached, reach, prepared, diagnostics, unreached = [], {}, {}, {}, {}
        for raw in payload["positions"]:
            context = PositionContext.model_validate(raw)
            try:
                model = self.registry.model_for(context)
            except (UnknownInstrumentType, UnknownModel) as exc:
                # A position no plugin can calculate stays in the run with the reason.
                reached.append(context)
                reach[context.position_id] = ["no_model"]
                diagnostics[context.position_id] = Diagnostics(
                    items=[{"code": "no_model", "severity": "error", "message": str(exc)}],
                    blocked_status="invalid",
                )
                prepared[context.position_id] = None
                continue
            problems = schema_problems(context, self.registry)
            if problems:
                reached.append(context)
                reach[context.position_id] = ["schema"]
                diagnostics[context.position_id] = Diagnostics(
                    items=problems, blocked_status="invalid"
                )
                prepared[context.position_id] = None
                continue
            needs = model.requirements(context, options)
            why = exposure.reasons(context, needs, graph, parameters, self.registry)
            missing_scenario = exposure.missing_direct_scenario(
                context, needs, graph, parameters, self.registry
            )
            data, missing = self.resolver.resolve(
                context, needs, as_of=as_of, snapshot_id=payload["snapshot_id"]
            )
            item = PreparedInputs(
                context=context,
                model_id=model.model_id,
                as_of=as_of,
                horizon=options.horizon,
                snapshot_id=payload["snapshot_id"],
                data=data,
                missing=missing,
                requirements=needs,
                options=options.options,
            )
            found = model.validate(item)
            if not why and not missing_scenario:
                unreached[context.position_id] = dict(found.exposures)
                continue
            reached.append(context)
            reach[context.position_id] = why or ["unmapped_model_factors"]
            found = with_required_data(found, needs, missing)
            if missing_scenario:
                found = found.model_copy(
                    update={
                        "items": [
                            *found.items,
                            Diagnostic(
                                code="scenario_factor_missing",
                                severity="error",
                                path="/macro_parameters",
                                message="Граф указывает влияние на позицию. Сценарий не задаёт "
                                "изменения факторов его модели. Добавьте параметр во вкладке "
                                "«Сценарий и граф»: " + "; ".join(missing_scenario) + ". "
                                "Отсутствие расчёта не означает отсутствие потерь.",
                            ),
                        ],
                        "blocked_status": "needs_review",
                    }
                )
            prepared[context.position_id] = item
            diagnostics[context.position_id] = found
        reached.sort(key=lambda c: c.position_id)
        return {
            "positions": [c.model_dump(mode="json") for c in reached],
            "reach": reach,
            "prepared": {
                k: None if v is None else v.model_dump(mode="json") for k, v in prepared.items()
            },
            "diagnostics": {k: v.model_dump(mode="json") for k, v in diagnostics.items()},
            "unreached_exposures": unreached,
        }
