"""mcp-runs: what a calculated run says about itself, for the explanation of its results.

Every tool is bound to the run the calling node works for: its ``run_id`` must be the run
of the audit context, so an explanation cannot read another run. The LLM sees the tools
without ``run_id``; the explanation agent adds it. Numbers come with their unit, label and
metric path, so an answer can cite them; quantiles always come as P5/P50/P95 together.
"""

from sqlalchemy import select

from msa.contracts import CalculationResult, PortfolioResult
from msa.db.models import tables_for
from msa.db.repositories.runs import ApplicationRunRepository
from msa.engine.catalog import describe_model as describe
from msa.platform.registry import registry as current
from msa.reporting.numbers import pointer_token, resolve_pointer
from msa.reporting.tree import metric_tree
from msa.reporting.wording import flag

from ..audit import CallContext

#: Positions the run summary lists; the rest are counted and reachable by id.
SUMMARY_POSITIONS = 40


def register(tool, services):
    @tool
    def get_run_summary(run_id: str, audit: CallContext) -> dict:
        """The run at a glance: portfolio, dates, scenario, portfolio slices and positions.

        Slices give P5/P50/P95 of the loss, ES95 and the covered share of exposure;
        positions give their status and headline metrics with metric paths.
        """
        _bound(run_id, audit)
        return summary(_load(services, run_id), current())

    @tool
    def get_position_metrics(run_id: str, position_id: str, audit: CallContext) -> dict:
        """One position: every metric with unit and path, flags in words, data and model."""
        _bound(run_id, audit)
        return position(_load(services, run_id), position_id, current())

    @tool
    def get_metric_provenance(run_id: str, metric_path: str, audit: CallContext) -> dict:
        """Where a number comes from: model and version, data snapshot, scenario, sources."""
        _bound(run_id, audit)
        return provenance(_load(services, run_id), metric_path, current())

    @tool
    def describe_model(run_id: str, model_id: str, audit: CallContext) -> dict:
        """A calculation model: what it calculates, its metrics with units, its limits."""
        _bound(run_id, audit)
        item = describe(model_id)
        item.pop("input_schema", None)
        return item


def _bound(run_id, audit):
    if audit.run_id != run_id:
        raise PermissionError(f"the tool is bound to run {audit.run_id}, not {run_id}")


def _load(services, run_id) -> dict:
    with services.read_session() as session:
        repository = ApplicationRunRepository(session)
        run = repository.get_run(run_id)
        rows = [dict(row) for row in repository.results(run_id)]
        job_table = tables_for(session)["api_job"]
        job = (
            session.execute(select(job_table.c.payload).where(job_table.c.job_id == run_id))
            .scalars()
            .first()
        )
        journal = repository.list_node_results(run_id)
    results = [
        CalculationResult.model_validate(r["payload"]) for r in rows if r["kind"] == "position"
    ]
    portfolio = next((r["payload"] for r in rows if r["kind"] == "portfolio"), None)
    if not results:
        raise LookupError(f"run {run_id} has no calculated results")
    return {
        "run": run,
        "payload": job or {},
        "results": sorted(results, key=lambda r: r.position_id),
        "portfolio": None if portfolio is None else PortfolioResult.model_validate(portfolio),
        "journal": journal,
    }


def _tree(data, registry):
    from msa.agents.advisory import channel_factors

    scenario = data["run"].get("scenario") or {}
    return metric_tree(
        data["results"],
        data["portfolio"],
        registry=registry,
        context={"channel_factors": channel_factors(scenario.get("parameters"))},
    )


def _metric(result, metric_id, registry) -> dict:
    value = result.metrics[metric_id]
    spec = registry.metrics.get(metric_id)
    base = f"/positions/{pointer_token(result.position_id)}/metrics/{metric_id}"
    item = {
        "metric_id": metric_id,
        "label": spec.label if spec else metric_id,
        "unit": value.unit,
    }
    if spec is not None:
        item.update(period=spec.period, direction=spec.direction)
    if value.quantiles is not None:
        q = value.quantiles
        item.update(p05=q.p05, p50=q.p50, p95=q.p95, path_p50=f"{base}/p50")
        if q.es95 is not None:
            item["es95"] = q.es95
    if value.value is not None:
        item.update(value=value.value, path_value=f"{base}/value")
    return item


def _flags(codes, registry) -> list[dict]:
    wording = registry.flag_wording()
    return [{"code": code, "text": flag(code, wording)} for code in dict.fromkeys(codes)]


def _slice(slice_id, item, registry) -> dict:
    spec = registry.slices.get(slice_id)
    base = f"/portfolio/slices/{pointer_token(slice_id)}"
    out = {
        "slice_id": slice_id,
        "label": spec.label if spec else slice_id,
        "measure": spec.measure_label if spec else item.measure,
        "unit": item.unit,
        "status": item.status,
        "coverage_basis": item.coverage.basis,
        "covered_percent": item.coverage.covered_share * 100,
        "path_covered_percent": f"{base}/covered_percent",
        "included": len(item.included),
        "excluded": [
            {"position_id": e.position_id, "status": e.status, "reason": e.reason}
            for e in item.excluded
        ],
        "flags": _flags(item.flags, registry),
    }
    if item.loss_quantiles is not None:
        q = item.loss_quantiles
        out.update(
            p05=q.p05,
            p50=q.p50,
            p95=q.p95,
            es95=item.expected_shortfall_95,
            mean=item.mean_loss,
            sum_of_individual_p95=item.sum_of_individual_p95,
            path_p50=f"{base}/loss_quantiles/p50",
        )
    return out


def _headline(result, registry) -> list[str]:
    view = registry.view_for(result.instrument_type)
    chosen = list(view.summary_metrics) if view and view.summary_metrics else []
    if not chosen and result.model_id in registry.models:
        chosen = list(registry.models[result.model_id].required_metrics)
    return [m for m in chosen if m in result.metrics]


def summary(data, registry) -> dict:
    run, payload, portfolio = data["run"], data["payload"], data["portfolio"]
    results = data["results"]
    weight = {}
    if portfolio is not None:
        for item in portfolio.slices.values():
            for c in item.contributions:
                weight[c.position_id] = max(
                    weight.get(c.position_id, 0.0), c.expected_shortfall_contribution
                )
    ordered = sorted(results, key=lambda r: (-weight.get(r.position_id, 0.0), r.position_id))
    names = payload.get("position_names") or {}
    scenario = (run.get("scenario") or {}).get("parameters") or {}
    counts = {"positions": len(results)}
    for state in ("completed", "not_run", "failed"):
        counts[state] = sum(r.execution == state for r in results)
    return {
        "run_id": run["run_id"],
        "portfolio_id": run.get("portfolio_id"),
        "status": run.get("status"),
        "as_of": payload.get("as_of"),
        "horizon_months": payload.get("horizon"),
        "base_currency": payload.get("base_currency"),
        "snapshot_id": run.get("snapshot_id"),
        "scenario_id": run.get("scenario_id"),
        "scenario": [
            {
                "name": name,
                **{
                    k: v
                    for k, v in item.items()
                    if k
                    in {
                        "label",
                        "kind",
                        "value",
                        "low",
                        "mode",
                        "high",
                        "mean",
                        "sigma",
                        "unit",
                        "factor",
                        "key",
                        "channel",
                    }
                },
            }
            for name, item in sorted(scenario.items())
        ],
        "counts": counts,
        "portfolio_status": None if portfolio is None else portfolio.status,
        "slices": []
        if portfolio is None
        else [_slice(sid, item, registry) for sid, item in sorted(portfolio.slices.items())],
        "not_aggregated": []
        if portfolio is None
        else [
            {"position_id": e.position_id, "status": e.status, "reason": e.reason}
            for e in portfolio.not_aggregated
        ],
        "positions": [
            {
                "position_id": r.position_id,
                "name": names.get(r.position_id, ""),
                "instrument_type": r.instrument_type,
                "type_label": registry.instrument_types[r.instrument_type].label
                if r.instrument_type in registry.instrument_types
                else r.instrument_type,
                "model_id": r.model_id,
                "execution": r.execution,
                "status": r.status,
                "metrics": [_metric(r, m, registry) for m in _headline(r, registry)],
            }
            for r in ordered[:SUMMARY_POSITIONS]
        ],
        "positions_shown": min(len(ordered), SUMMARY_POSITIONS),
        "report_summary": (run.get("report") or {}).get("summary"),
    }


def _result(data, position_id) -> CalculationResult:
    found = next((r for r in data["results"] if r.position_id == position_id), None)
    if found is None:
        raise KeyError(f"{position_id} is not a position of run {data['run']['run_id']}")
    return found


def position(data, position_id, registry) -> dict:
    result = _result(data, position_id)
    projection = _tree(data, registry)["positions"][position_id]
    projection.pop("metrics", None)
    names = data["payload"].get("position_names") or {}
    return {
        "position_id": position_id,
        "name": names.get(position_id, ""),
        "instrument_type": result.instrument_type,
        "model": f"{result.model_id}@{result.model_version}",
        "execution": result.execution,
        "status": result.status,
        "applicability": result.applicability,
        "data_quality": result.data_quality.model_dump(mode="json"),
        "metrics": [_metric(result, m, registry) for m in sorted(result.metrics)],
        "flags": _flags(result.flags, registry),
        "assumptions": _flags(result.assumptions, registry),
        "diagnostics": [
            {"code": d.code, "severity": d.severity, "message": d.message}
            for d in result.diagnostics
        ],
        "slices": [
            {
                "slice_id": c.slice_id,
                "exposure": c.exposure,
                "basis": c.exposure_basis,
                "admission": c.admission,
            }
            for c in result.contributions
        ],
        # The plugin's keyed view of its details: covenants, channels, factor contributions.
        "details": projection,
    }


def provenance(data, metric_path, registry) -> dict:
    tree = _tree(data, registry)
    try:
        value = resolve_pointer(tree, metric_path)
    except (KeyError, TypeError, IndexError):
        raise KeyError(f"no number at {metric_path}") from None
    run = data["run"]
    out = {
        "metric_path": metric_path,
        "value": value,
        "scenario_id": run.get("scenario_id"),
        "macro_draws_sha256": run.get("macro_draws_sha256"),
        "snapshot_id": run.get("snapshot_id"),
    }
    parts = metric_path.split("/")
    if metric_path.startswith("/positions/"):
        result = _result(data, parts[2].replace("~1", "/").replace("~0", "~"))
        out.update(
            position_id=result.position_id,
            model=f"{result.model_id}@{result.model_version}",
            plugin=f"{result.plugin_id}@{result.plugin_version}",
            input_sources=result.input_sources,
            sources=[
                {"kind": s.kind, "source_id": s.source_id, "locator": s.locator}
                for s in result.sources
            ],
            assumptions=_flags(result.assumptions, registry),
            flags=_flags(result.flags, registry),
        )
    elif metric_path.startswith("/portfolio/slices/") and data["portfolio"] is not None:
        slice_id = parts[3].replace("~1", "/").replace("~0", "~")
        item = data["portfolio"].slices[slice_id]
        out.update(
            slice_id=slice_id,
            included=item.included,
            excluded=[e.model_dump(mode="json") for e in item.excluded],
            coverage=item.coverage.model_dump(mode="json"),
            method="Потери позиций складываются в каждой реализации сценария, "
            "затем берутся квантили суммы.",
        )
    report = run.get("report") or {}
    out["cited_in_report"] = any(
        ref.get("metric_path") == metric_path for ref in report.get("numbers", [])
    )
    if out["cited_in_report"]:
        from msa.reporting.trace import trace_number

        class Journal:
            def list_node_results(self, run_id):
                return data["journal"]

        try:
            lineage = trace_number(run["run_id"], metric_path, Journal(), registry)
            out["lineage"] = lineage["lineage"]
        except KeyError:
            out["lineage"] = []
    return out
