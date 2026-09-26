import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from uuid import uuid4

from sqlalchemy import select, update

from msa.agents.advisory import channel_factors
from msa.agents.causal_output import scenario_violations
from msa.agents.ingest import fragment
from msa.contracts import Report
from msa.contracts.domain import contexts
from msa.db.models import tables_for
from msa.db.repositories.runs import (
    ApplicationRunRepository,
    DurableRunRepository,
    json_payload,
)
from msa.db.repositories.snapshots import SnapshotsRepository
from msa.engine.exposure import scenario_coverage
from msa.graph.checkpoint import run_config
from msa.graph.compiler import describe
from msa.graph.interrupts import pending_interrupt, resume_run, start_run
from msa.graph.workflow import build_graph
from msa.platform.registry import registry
from msa.plugin_sdk.model import RunOptions
from msa.reporting.trace import trace_number
from msa.reporting.tree import metric_tree

from .agent_service import FixedDocument
from .problem import Problem

ACTIVE = {"queued", "running"}
HORIZON = 12


class PluginsChanged(RuntimeError):
    """The run started on other plugin versions; it does not continue on this code."""


class RunService:
    """One API process owns execution; checkpoints and HTTP state survive its restart."""

    def __init__(self, db, agents, checkpointer, limiter):
        self.db, self.agents, self.checkpointer, self.limiter = db, agents, checkpointer, limiter
        self.pool = ThreadPoolExecutor(max_workers=5, thread_name_prefix="msa-run")

    def close(self):
        self.pool.shutdown(wait=True)

    def job(self, scope, run_id):
        return self.db.get(scope, "api_job", {"job_id": run_id})

    def scenario_coverage(self, scope, payload, graph, parameters):
        return scenario_coverage(
            payload.get("portfolio_positions") or [],
            graph,
            parameters,
            RunOptions(
                as_of=payload["as_of"],
                horizon=payload.get("horizon", HORIZON),
                base_currency=payload.get("base_currency", "RUB"),
                options=self.agents.options(scope),
            ),
            registry(),
        )

    def graph(self, scope, job):
        from msa.contracts import SourceDocument

        payload = job["payload"]
        agents = self.agents.agents(scope, portfolio_id=payload["portfolio_id"])
        agents = replace(
            agents, ingest=FixedDocument(SourceDocument.model_validate(payload["document"]))
        )
        return build_graph(
            self.checkpointer,
            agents=agents,
            repository=DurableRunRepository(self.db, scope),
            auto_approve_demo=scope == "demo" and payload["auto_approve"],
            registry=registry(),
            options=self.agents.options(scope),
            enabled=payload.get("agents") or (),
            workflow_id=payload.get("workflow_id", "stress_test"),
        )

    def prepare(self, scope, request, principal, *, run_id=None):
        if scope == "production" and self.agents.llm()["external"]:
            # The bank portfolio never reaches a model outside the perimeter.
            raise Problem(409, "Внешняя LLM: разрешены только синтетические демо-портфели")
        if request.auto_approve and scope != "demo":
            raise Problem(403, "Automatic approval exists only in the demo namespace")
        reg = registry()
        if request.workflow_id not in reg.workflows:
            raise Problem(422, f"Неизвестный процесс {request.workflow_id}")
        workflow = reg.workflows[request.workflow_id]
        unknown = sorted(set(request.agents) - set(reg.agents))
        if unknown:
            raise Problem(422, f"Неизвестные агенты: {', '.join(unknown)}")
        bundle = self.agents.bundle(scope, request.portfolio_id)
        chosen = contexts(bundle)
        position_ids = request.position_ids
        if position_ids is not None:
            known = {c.position_id for c in chosen}
            if len(set(position_ids)) != len(position_ids) or set(position_ids) - known:
                raise Problem(422, "position_ids must uniquely identify positions of the portfolio")
            chosen = [c for c in chosen if c.position_id in position_ids]
        # An explicitly chosen model replaces the type's default for that position.
        models = {}
        for context in chosen:
            choice = request.models.get(context.position_id) or request.models.get(
                context.instrument.instrument_type
            )
            if choice is not None:
                model = reg.models.get(choice)
                if (
                    model is None
                    or context.instrument.instrument_type not in model.instrument_types
                ):
                    raise Problem(
                        422, f"Модель {choice} не рассчитывает позицию {context.position_id}"
                    )
                context.position.model_id = choice
            try:
                model = reg.model_for(context)
            except KeyError as exc:
                raise Problem(422, str(exc.args[0])) from None
            models[context.position_id] = f"{model.model_id}@{model.version}"
        snapshot_id = request.snapshot_id or bundle.portfolio.snapshot_id
        if not snapshot_id:
            raise Problem(422, "Портфелю не назначен снимок данных; укажите snapshot_id")
        with self.db.session(scope) as session:
            if not SnapshotsRepository(session).exists(snapshot_id):
                raise Problem(422, f"Снимок данных {snapshot_id} не найден")
        as_of = request.as_of or bundle.portfolio.as_of or date.today()
        document = self.agents.document(scope, request.event)
        text = "\n\n".join(f.text for f in document.fragments) or "Unparsed document"
        scenario = request.scenario
        if scenario:
            # The causal agent cites the scenario words like any other fragment of the event.
            document = document.model_copy(
                update={"fragments": [*document.fragments, fragment(scenario, "scenario")]}
            )
        run_id = run_id or str(uuid4())
        names = self.agents.names(scope, request.portfolio_id)
        payload = {
            "run_id": run_id,
            "workflow_id": workflow.workflow_id,
            "workflow_version": workflow.version,
            "agents": sorted(request.agents),
            "plugins": reg.versions(),
            "models": models,
            "portfolio_id": request.portfolio_id,
            "snapshot_id": snapshot_id,
            "base_currency": bundle.portfolio.base_currency,
            "text": text,
            "scenario_text": scenario,
            "document": json_payload(document),
            "portfolio_positions": [c.model_dump(mode="json") for c in chosen],
            "position_names": {c.position_id: names.get(c.position_id, "") for c in chosen},
            "seed": request.seed,
            "mc_points": request.mc_points,
            "horizon": HORIZON,
            "mode": scope,
            "as_of": as_of.isoformat(),
            "auto_approve": request.auto_approve,
            "request_graph_review": request.request_graph_review,
        }
        return {
            "job_id": run_id,
            "kind": "run",
            "principal": principal.key_id,
            "payload": payload,
            "status": "queued",
            "state": {},
            "error": None,
        }

    def persist(self, scope, job, actor):
        with self.db.session(scope) as session:
            self.persist_in_session(session, job, actor)

    def persist_in_session(self, session, job, actor):
        from msa.db.repositories.common import upsert

        payload = job["payload"]
        ApplicationRunRepository(session).create_run(
            job["job_id"],
            payload["text"],
            seed=payload["seed"],
            mc_points=payload["mc_points"],
            workflow_id=payload["workflow_id"],
            workflow_version=payload["workflow_version"],
            portfolio_id=payload["portfolio_id"],
            snapshot_id=payload["snapshot_id"],
            position_ids=[p["position"]["position_id"] for p in payload["portfolio_positions"]],
            plugins=payload["plugins"],
            models=payload["models"],
            versions=self.agents.stamp(),
            actor=actor,
        )
        upsert(session, tables_for(session)["api_job"], job)

    def submit(self, scope, request, principal):
        token = str(uuid4())
        self.limiter.reserve(scope, principal.key_id, "run", tokens=[token])
        try:
            job = self.prepare(scope, request, principal, run_id=token)
            self.persist(scope, job, principal.actor)
            self.pool.submit(self.execute, scope, token)
        except Exception:
            self.limiter.release(scope, principal.key_id, token)
            raise
        return self.status(scope, token)

    def execute(self, scope, run_id):
        job = self.job(scope, run_id)
        try:
            job["status"] = "running"
            self.db.put(scope, "api_job", job)
            recorded = job["payload"].get("plugins") or {}
            current = registry().versions()
            if recorded and recorded != current:
                # A run is fixed to the code it started on; it does not continue on another.
                raise PluginsChanged(f"plugin versions changed since the run started: {recorded}")
            graph = self.graph(scope, job)
            snapshot = graph.get_state(run_config(run_id))
            answer = job["payload"].get("resume")
            if answer is not None and pending_interrupt(graph, run_id):
                state = resume_run(graph, run_id, answer)
            elif snapshot.values:
                state = (
                    graph.invoke(None, config=run_config(run_id))
                    if snapshot.next and not pending_interrupt(graph, run_id)
                    else snapshot.values
                )
            else:
                state = start_run(graph, self.graph_input(job["payload"]))
            self.save_state(scope, job, graph, state)
        except Exception as exc:
            logging.getLogger(__name__).exception("Run %s failed", run_id)
            # A code change is the analyst's to know; other failures are in the server log.
            error = (
                str(exc)
                if isinstance(exc, PluginsChanged)
                else "Run failed; consult the server log"
            )
            job.update(status="failed", error=error)
            self.db.put(scope, "api_job", job)
            DurableRunRepository(self.db, scope).update_run(run_id, status="failed")
        finally:
            self.limiter.release(scope, job["principal"], run_id)

    @staticmethod
    def graph_input(payload):
        keys = (
            "run_id",
            "text",
            "seed",
            "mc_points",
            "horizon",
            "mode",
            "as_of",
            "portfolio_id",
            "snapshot_id",
            "base_currency",
            "portfolio_positions",
            "position_names",
            "request_graph_review",
        )
        return {key: payload[key] for key in keys}

    def save_state(self, scope, job, graph, state):
        run_id = job["job_id"]
        pending = pending_interrupt(graph, run_id)
        status = (
            pending[0]["payload"]["kind"]
            if pending
            else {"published": "completed", "completed": "completed", "rejected": "rejected"}.get(
                state.get("status"), "failed"
            )
        )
        projection = {
            "pending_interrupt": pending,
            "errors": state.get("errors", []),
            "node": state.get("trace", [None])[-1],
            "attempt": state.get("attempts", 0),
            # What the causal agent understood from the event; served with the artifacts.
            "scenario": {
                "passport": state.get("event_passport"),
                "numbers": state.get("event_parameters") or {},
                "parameters": state.get("macro_parameters") or {},
                "confirmed": state.get("scenario_confirmed", False),
                "required": state.get("scenario_required", False),
                "revision": state.get("graph_revision", 0),
            },
            "reach": state.get("reach") or {},
            "diagnostics": state.get("diagnostics") or {},
            "extensions": state.get("extensions") or {},
        }
        with self.db.session(scope) as session:
            repository = ApplicationRunRepository(session)
            report = state.get("report")
            confirmed = state.get("scenario_confirmed") and state.get("scenario_set")
            repository.update_run(
                run_id,
                graph=state.get("graph") or None,
                macro_draws_sha256=state.get("macro_draws_sha256"),
                scenario_id=state.get("scenario_id"),
                scenario={
                    "revision": state.get("graph_revision", 0),
                    "parameters": state.get("macro_parameters") or {},
                    "set": state.get("scenario_set"),
                }
                if confirmed
                else None,
                report=report,
            )
            if report and report.get("approved_by"):
                parsed = Report.model_validate(report)
                repository.set_approval(run_id, parsed.approved_by, parsed.approved_at)
            repository.delete_results(run_id, ("position", "portfolio"))
            db_status = {
                "human_fix_graph": "awaiting_graph_fix",
                "human_approval": "awaiting_approval",
                "completed": "completed",
                "rejected": "rejected",
                "failed": "needs_review",
            }[status]
            repository.update_run(run_id, status=db_status)
            for result in state.get("sorted_results", []):
                repository.save_result(run_id, "position", result["position_id"], result)
            if state.get("portfolio_result"):
                repository.save_result(run_id, "portfolio", run_id, state["portfolio_result"])
        job.update(status=status, state=projection, error=None)
        job["payload"].pop("resume", None)
        self.db.put(scope, "api_job", job)

    def status(self, scope, run_id):
        job = self.job(scope, run_id)
        if job["kind"] != "run":
            raise KeyError(run_id)
        row = DurableRunRepository(self.db, scope).get_run(run_id)
        base = "/v1/demo/runs" if scope == "demo" else "/v1/runs"
        hidden = {"scenario", "reach", "diagnostics", "extensions"}
        return {
            "run_id": run_id,
            "status": job["status"],
            **{key: value for key, value in job["state"].items() if key not in hidden},
            "error": job["error"],
            "workflow_id": row["workflow_id"],
            "workflow_version": row["workflow_version"],
            "versions": row["versions"],
            "plugins": row["plugins"],
            "snapshot_id": row["snapshot_id"],
            "scenario_id": row["scenario_id"],
            "macro_draws_sha256": row["macro_draws_sha256"],
            "report_url": f"{base}/{run_id}/report" if row["report"] else None,
        }

    def list_runs(self, scope, limit=100):
        """Newest runs first, with what the screens need to route people to their next step."""
        with self.db.session(scope) as session:
            tables = tables_for(session)
            run, job, audit = tables["run"], tables["api_job"], tables["audit_log"]
            rows = [
                dict(row)
                for row in session.execute(
                    select(
                        run.c.run_id,
                        run.c.event_text,
                        run.c.created_at,
                        run.c.updated_at,
                        run.c.approved_by,
                        run.c.approved_at,
                        run.c.portfolio_id,
                        run.c.workflow_id,
                        job.c.status,
                        job.c.error,
                    )
                    .join(job, job.c.job_id == run.c.run_id)
                    .where(job.c.kind == "run")
                    .order_by(run.c.created_at.desc())
                    .limit(limit)
                ).mappings()
            ]
            authors = dict(
                session.execute(
                    select(audit.c.run_id, audit.c.actor).where(
                        audit.c.action == "run.created",
                        audit.c.run_id.in_([row["run_id"] for row in rows]),
                    )
                ).all()
            )
        for row in rows:
            row["created_by"] = authors.get(row["run_id"])
            # Document events carry the whole text; the list needs only a recognizable start.
            if len(row["event_text"]) > 300:
                row["event_text"] = row["event_text"][:300] + "…"
        return rows

    def report(self, scope, run_id):
        self.status(scope, run_id)
        row = DurableRunRepository(self.db, scope).get_run(run_id)
        if row["report"] is None:
            raise Problem(409, "Report is not ready")
        return row["report"]

    def resume(self, scope, run_id, request, principal):
        from .auth import require_role

        status = self.status(scope, run_id)["status"]
        details = {"kind": status}
        if status == "human_approval" and request.approved is not None:
            require_role(principal, "risk_manager", *(["demo"] if scope == "demo" else []))
            answer = {
                "approved": request.approved,
                "approved_by": principal.actor,
                "returned": request.returned,
                "reason": request.reason,
            }
            # A report that went back or died is reviewable only with its reason on record.
            negative = "returned" if request.returned else "rejected"
            details |= {
                "outcome": "approved" if request.approved else negative,
                "reason": request.reason,
            }
        elif status == "human_fix_graph" and request.graph is not None:
            require_role(principal, "analyst", *(["demo"] if scope == "demo" else []))
            from msa.validators import validate

            stop = self.status(scope, run_id)["pending_interrupt"][0]["payload"]
            graph = request.graph.model_dump(mode="json")
            parameters = (
                stop.get("macro_parameters") or {}
                if request.macro_parameters is None
                else {k: v.model_dump(mode="json") for k, v in request.macro_parameters.items()}
            )
            failures = [
                v.model_dump(exclude={"ok"})
                for v in validate("TransmissionGraph", request.graph)
                if not v.ok
            ] + [
                {k: v for k, v in problem.items() if k != "ok"}
                for problem in scenario_violations(
                    parameters, graph, required=stop.get("scenario_required", False)
                )
            ]
            if failures:
                raise Problem(422, "Invalid graph edit", violations=failures)
            missing = self.scenario_coverage(
                scope, self.job(scope, run_id)["payload"], graph, parameters
            )
            if missing:
                raise Problem(422, "Сценарий не охватывает затронутые позиции", violations=missing)
            answer = {"graph": graph}
            if request.macro_parameters is not None:
                answer["macro_parameters"] = parameters
        else:
            raise Problem(409, "Resume payload does not match the pending interrupt")
        self.limiter.reserve(scope, principal.key_id, "run", tokens=[run_id], count=0)
        try:
            with self.db.session(scope) as session:
                table = tables_for(session)["api_job"]
                job = dict(
                    session.execute(select(table).where(table.c.job_id == run_id).with_for_update())
                    .mappings()
                    .one()
                )
                if job["status"] != status:
                    raise Problem(409, "Run is already resuming")
                job["payload"] = {**job["payload"], "resume": answer}
                job.update(status="queued", principal=principal.key_id)
                session.execute(update(table).where(table.c.job_id == run_id).values(**job))
            self.db.audit(scope, principal.actor, "run.resume", run_id=run_id, details=details)
            self.pool.submit(self.execute, scope, run_id)
        except Exception:
            self.limiter.release(scope, principal.key_id, run_id)
            raise
        return self.status(scope, run_id)

    def names(self, scope, run_id):
        return self.job(scope, run_id)["payload"].get("position_names") or {}

    def results(self, scope, run_id):
        journal = DurableRunRepository(self.db, scope)
        rows = [dict(row) for row in journal.results(run_id)]
        results = [r["payload"] for r in rows if r["kind"] == "position"]
        portfolio = next((r["payload"] for r in rows if r["kind"] == "portfolio"), None)
        return results, portfolio

    def artifacts(self, scope, run_id):
        """Everything the analyst screens render, read from the run, its job and results."""
        status = self.status(scope, run_id)
        journal = DurableRunRepository(self.db, scope)
        pending = status.get("pending_interrupt") or []
        row = journal.get_run(run_id)
        graph = (
            pending[0]["payload"]["graph"]
            if pending and pending[0]["payload"]["kind"] == "human_fix_graph"
            else row["graph"]
        )
        job = self.job(scope, run_id)
        payload, state = job["payload"], job["state"]
        results, portfolio = self.results(scope, run_id)
        scenario = state.get("scenario", {})
        reg = registry()
        workflow = reg.workflows.get(row["workflow_id"])
        with self.db.session(scope) as session:
            try:
                snapshot = SnapshotsRepository(session).header(row["snapshot_id"])
            except KeyError:
                snapshot = None
        return {
            "run_id": run_id,
            "status": status["status"],
            "portfolio_id": payload["portfolio_id"],
            "base_currency": payload.get("base_currency", "RUB"),
            "as_of": payload["as_of"],
            "event_text": payload["text"],
            "scenario": {**scenario, "text": payload.get("scenario_text")},
            "scenario_warnings": self.scenario_coverage(
                scope, payload, graph, scenario.get("parameters") or {}
            )
            if graph
            else [],
            "approved_by": row["approved_by"],
            "approved_at": row["approved_at"],
            "position_names": payload.get("position_names") or {},
            "graph": graph,
            "document": payload["document"],
            "positions": payload["portfolio_positions"],
            "reach": state.get("reach") or {},
            "diagnostics": state.get("diagnostics") or {},
            "results": results,
            "portfolio": portfolio,
            # The keyed view the report cites; screens resolve metric paths against it.
            "metric_tree": metric_tree(
                results,
                portfolio,
                registry=reg,
                context={"channel_factors": channel_factors(scenario.get("parameters"))},
            ),
            "extensions": state.get("extensions") or {},
            "workflow": describe(workflow, reg, payload.get("agents") or ())
            if workflow is not None
            else None,
            "plugins": row["plugins"],
            "models": payload.get("models") or {},
            "snapshot": None
            if snapshot is None
            else {
                "snapshot_id": snapshot["snapshot_id"],
                "as_of": snapshot["as_of"],
                "label": snapshot["label"],
                "kind": snapshot["kind"],
                "sha256": snapshot["sha256"],
            },
            "notes": {
                plugin_id: plugin.notes(self.agents.options(scope))
                for plugin_id, plugin in reg.plugins.items()
                if plugin.notes is not None
            },
        }

    def trace(self, scope, run_id):
        report = Report.model_validate(self.report(scope, run_id))
        journal = DurableRunRepository(self.db, scope)
        return {
            "run_id": run_id,
            "trace_id": run_id,
            "numbers": [trace_number(run_id, ref.metric_path, journal) for ref in report.numbers],
            "nodes": [
                {"node": r["node"], "attempt": r["attempt"]}
                for r in journal.list_node_results(run_id)
            ],
        }

    def activity(self, scope, run_id):
        """LLM answers and MCP tool calls of the run, in the order they happened."""
        from msa.db.audit import AuditLog

        self.status(scope, run_id)
        with self.db.session(scope) as session:
            rows = AuditLog(session).for_run(run_id)
        items = []
        for row in rows:
            kind, _, outcome = row["action"].partition(".")
            if kind not in {"llm", "tool"}:
                continue
            details = row["details"] or {}
            items.append(
                {
                    "at": row["occurred_at"],
                    "kind": kind,
                    "status": outcome,
                    "node": row["node"],
                    "attempt": row["attempt"],
                    "name": row["tool"] or details.get("model"),
                    # Who asked for the call: the workflow itself or an LLM choosing a tool.
                    "initiator": details.get("initiator", "workflow"),
                    "details": details,
                }
            )

        def total(kind, field):
            return sum((i["details"].get(field) or 0) for i in items if i["kind"] == kind)

        llm = [i for i in items if i["kind"] == "llm"]
        return {
            "run_id": run_id,
            "llm": {
                "calls": len(llm),
                "failed": sum(i["status"] != "completed" for i in llm),
                "prompt_tokens": total("llm", "prompt_tokens"),
                "completion_tokens": total("llm", "completion_tokens"),
                "duration_ms": total("llm", "duration_ms"),
            },
            "tools": {
                "calls": sum(i["kind"] == "tool" for i in items),
                "failed": sum(i["kind"] == "tool" and i["status"] != "completed" for i in items),
                "by_llm": sum(i["kind"] == "tool" and i["initiator"] == "llm" for i in items),
                "duration_ms": total("tool", "duration_ms"),
            },
            "items": items,
        }

    def recover(self):
        # Invoke once at startup, before serving requests. Deploy with one execution worker.
        for scope in ("production", "demo"):
            self.limiter.reconcile(scope)
            with self.db.session(scope) as session:
                table = tables_for(session)["api_job"]
                jobs = [
                    dict(r)
                    for r in session.execute(
                        select(table).where(table.c.status.in_(ACTIVE))
                    ).mappings()
                ]
            for job in jobs:
                self.pool.submit(self.execute, scope, job["job_id"])
