"""The run catalog, its results and the per-node journal that makes runs resumable."""

import json
from threading import RLock
from typing import Protocol

from pydantic_core import to_jsonable_python


def json_payload(payload):
    return json.loads(json.dumps(to_jsonable_python(payload), allow_nan=False, sort_keys=True))


class RunRepository(Protocol):
    def get_node_result(self, run_id: str, node: str, attempt: int) -> dict | None: ...
    def node_identity(self, run_id: str, node: str, attempt: int) -> tuple | None: ...
    def upsert_node_result(
        self, run_id: str, node: str, attempt: int, payload: dict, **identity
    ) -> None: ...


class MemoryRunRepository:
    def __init__(self):
        self._results = {}
        self._identity = {}
        self._lock = RLock()

    def get_node_result(self, run_id, node, attempt):
        with self._lock:
            return json_payload(self._results.get((run_id, node, attempt)))

    def node_identity(self, run_id, node, attempt):
        with self._lock:
            return self._identity.get((run_id, node, attempt))

    def upsert_node_result(
        self, run_id, node, attempt, payload, *, agent_version=None, inputs_sha256=None
    ):
        with self._lock:
            self._results[run_id, node, attempt] = json_payload(payload)
            self._identity[run_id, node, attempt] = (agent_version, inputs_sha256)

    def list_node_results(self, run_id):
        with self._lock:
            return [
                {"node": node, "attempt": attempt, "payload": json_payload(payload)}
                for (run, node, attempt), payload in sorted(self._results.items())
                if run == run_id
            ]


class ApplicationRunRepository:
    """Run catalog and journal inside one SQLAlchemy session (one transaction).

    The graph uses DurableRunRepository below: every node's journal entry commits in its own
    transaction before the graph moves on.
    """

    def __init__(self, session):
        from msa.db.models import tables_for

        self.session = session
        self.tables = tables_for(session)

    def create_run(
        self,
        run_id,
        event_text,
        *,
        seed,
        mc_points,
        workflow_id,
        workflow_version,
        portfolio_id,
        snapshot_id,
        position_ids=(),
        plugins=None,
        models=None,
        versions=None,
        actor="system",
    ):
        from hashlib import sha256

        from pydantic import TypeAdapter
        from sqlalchemy import insert

        from msa.contracts.common import McPoints, Seed, VersionStamp
        from msa.db.audit import AuditLog

        from .common import require_text

        require_text(run_id, "run_id")
        require_text(event_text, "event_text")
        for name, value in (
            ("workflow_id", workflow_id),
            ("workflow_version", workflow_version),
            ("portfolio_id", portfolio_id),
            ("snapshot_id", snapshot_id),
        ):
            require_text(value, name)
        seed = TypeAdapter(Seed).validate_python(seed)
        mc_points = TypeAdapter(McPoints).validate_python(mc_points)
        stamp = VersionStamp.model_validate(versions).model_dump(mode="json") if versions else {}
        self.session.execute(
            insert(self.tables["run"]).values(
                run_id=run_id,
                event_text=event_text,
                event_sha256=sha256(event_text.encode()).hexdigest(),
                seed=seed,
                mc_points=mc_points,
                status="created",
                workflow_id=workflow_id,
                workflow_version=workflow_version,
                portfolio_id=portfolio_id,
                snapshot_id=snapshot_id,
                position_ids=list(position_ids),
                plugins=dict(plugins or {}),
                models=dict(models or {}),
                versions=stamp,
            )
        )
        AuditLog(self.session).log(actor, "run.created", run_id)
        return self.get_run(run_id)

    def get_run(self, run_id):
        from sqlalchemy import select

        table = self.tables["run"]
        row = self.session.execute(select(table).where(table.c.run_id == run_id)).mappings().first()
        if row is None:
            raise KeyError(run_id)
        return dict(row)

    def update_run(
        self,
        run_id,
        *,
        status=None,
        graph=None,
        report=None,
        versions=None,
        macro_draws_sha256=None,
        scenario=None,
        scenario_id=None,
        models=None,
        actor="system",
    ):
        from pydantic import TypeAdapter
        from sqlalchemy import select, update

        from msa.contracts.common import Sha256, VersionStamp
        from msa.contracts.graph import TransmissionGraph
        from msa.contracts.report import Report
        from msa.db.audit import AuditLog
        from msa.db.base import utcnow

        table = self.tables["run"]
        current = (
            self.session.execute(select(table).where(table.c.run_id == run_id).with_for_update())
            .mappings()
            .first()
        )
        if current is None:
            raise KeyError(run_id)
        values = {"updated_at": utcnow()}
        if status is not None:
            allowed = {
                "created",
                "running",
                "awaiting_graph_fix",
                "awaiting_approval",
                "approved",
                "rejected",
                "published",
                "failed",
                "needs_review",
                "completed",
            }
            if status not in allowed:
                raise ValueError("Invalid run status")
            if status in {"approved", "published"} and not current["approved_by"]:
                raise ValueError("Approval is required")
            values["status"] = status
        if graph is not None:
            values["graph"] = TransmissionGraph.model_validate(graph).model_dump(mode="json")
        if report is not None:
            parsed = Report.model_validate(report)
            if parsed.run_id != run_id:
                raise ValueError("Report belongs to another run")
            if parsed.mode != self.session.info.get("data_scope", "production"):
                raise ValueError("Report mode does not match the data scope")
            parsed = parsed.model_copy(update={"approved_by": None, "approved_at": None})
            values["report"] = parsed.model_dump(mode="json")
            values.update(approved_by=None, approved_at=None, approved_report_sha256=None)
            values["status"] = "awaiting_approval"
        if versions is not None:
            values["versions"] = VersionStamp.model_validate(versions).model_dump(mode="json")
        if macro_draws_sha256 is not None:
            values["macro_draws_sha256"] = TypeAdapter(Sha256).validate_python(macro_draws_sha256)
        if scenario is not None:
            values["scenario"] = json_payload(scenario)
        if scenario_id is not None:
            values["scenario_id"] = TypeAdapter(Sha256).validate_python(scenario_id)
        if models is not None:
            values["models"] = dict(models)
        if any(
            key in values and values[key] != current[key]
            for key in ("graph", "versions", "macro_draws_sha256", "scenario", "scenario_id")
        ):
            if report is None:
                values.update(report=None, status="running")
            values.update(approved_by=None, approved_at=None, approved_report_sha256=None)
        if values.get("status") in {"approved", "published"}:
            from hashlib import sha256

            digest = sha256(
                json.dumps(
                    current["report"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode()
            ).hexdigest()
            if digest != current["approved_report_sha256"]:
                raise ValueError("Report no longer matches the recorded approval")
        self.session.execute(update(table).where(table.c.run_id == run_id).values(**values))
        AuditLog(self.session).log(actor, "run.updated", run_id, details={"fields": sorted(values)})

    def set_approval(self, run_id, who, when):
        from hashlib import sha256

        from sqlalchemy import select, update

        from msa.contracts.report import Report
        from msa.db.audit import AuditLog
        from msa.db.base import utc

        from .common import require_text

        require_text(who, "who")
        when = utc(when)
        if who == "demo:auto" and self.session.info.get("data_scope") != "demo":
            raise PermissionError("Automatic approval is only allowed in demo")
        table = self.tables["run"]
        row = (
            self.session.execute(select(table).where(table.c.run_id == run_id).with_for_update())
            .mappings()
            .first()
        )
        if row is None:
            raise KeyError(run_id)
        if row["report"] is None:
            raise ValueError("A report is required before approval")
        if row["approved_by"]:
            if row["approved_by"] != who:
                raise ValueError("Report is already approved by another actor")
            return
        report = {**row["report"], "approved_by": who, "approved_at": when.isoformat()}
        Report.model_validate(report)
        digest = sha256(
            json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        self.session.execute(
            update(table)
            .where(table.c.run_id == run_id)
            .values(
                approved_by=who,
                approved_at=when,
                approved_report_sha256=digest,
                report=report,
                status="approved",
                updated_at=when,
            )
        )
        AuditLog(self.session).log(who, "run.approved", run_id, details={"report_sha256": digest})

    def save_result(self, run_id, kind, artifact_id, payload):
        from msa.db.base import utcnow

        from .common import require_text, upsert

        self.get_run(run_id)
        require_text(kind, "kind")
        require_text(artifact_id, "artifact_id")
        upsert(
            self.session,
            self.tables["run_result"],
            {
                "run_id": run_id,
                "kind": kind,
                "artifact_id": artifact_id,
                "payload": json_payload(payload),
                "updated_at": utcnow(),
            },
        )

    def results(self, run_id):
        from sqlalchemy import select

        table = self.tables["run_result"]
        return list(
            self.session.execute(
                select(table)
                .where(table.c.run_id == run_id)
                .order_by(table.c.kind, table.c.artifact_id)
            ).mappings()
        )

    def delete_results(self, run_id, kinds):
        """Replaceable calculation artifacts must not survive a graph rerun."""
        from sqlalchemy import delete

        table = self.tables["run_result"]
        self.session.execute(
            delete(table).where(table.c.run_id == run_id, table.c.kind.in_(tuple(kinds)))
        )

    def get_node_result(self, run_id, node, attempt):
        from sqlalchemy import select

        table = self.tables["run_node_result"]
        payload = self.session.execute(
            select(table.c.payload).where(
                table.c.run_id == run_id, table.c.node == node, table.c.attempt == attempt
            )
        ).scalar_one_or_none()
        return json.loads(payload) if payload is not None else None

    def node_identity(self, run_id, node, attempt):
        """The (agent version, inputs hash) recorded with a node result, if any."""
        from sqlalchemy import select

        table = self.tables["run_node_result"]
        row = self.session.execute(
            select(table.c.agent_version, table.c.inputs_sha256).where(
                table.c.run_id == run_id, table.c.node == node, table.c.attempt == attempt
            )
        ).first()
        return None if row is None else (row[0], row[1])

    def upsert_node_result(
        self, run_id, node, attempt, payload, *, agent_version=None, inputs_sha256=None
    ):
        from msa.db.audit import AuditLog

        from .common import require_text, upsert

        require_text(run_id, "run_id")
        require_text(node, "node")
        if type(attempt) is not int or attempt < 1:
            raise ValueError("attempt must be a positive integer")
        data = json_payload(payload)
        if self.get_node_result(run_id, node, attempt) == data:
            return
        upsert(
            self.session,
            self.tables["run_node_result"],
            {
                "run_id": run_id,
                "node": node,
                "attempt": attempt,
                "payload": json.dumps(data, sort_keys=True),
                "agent_version": agent_version,
                "inputs_sha256": inputs_sha256,
            },
        )
        AuditLog(self.session).log("graph", "node.result", run_id, node, attempt)

    def list_node_results(self, run_id):
        from sqlalchemy import select

        table = self.tables["run_node_result"]
        rows = self.session.execute(
            select(table).where(table.c.run_id == run_id).order_by(table.c.node, table.c.attempt)
        ).mappings()
        return [
            {"node": row["node"], "attempt": row["attempt"], "payload": json.loads(row["payload"])}
            for row in rows
        ]


class DurableRunRepository:
    """The run repository for the graph and the services: every call is its own transaction.

    A node's journal entry commits before the graph moves on, so a restarted process resumes
    from the last finished node; parallel asset branches never share a transaction.
    """

    def __init__(self, db, scope):
        self.db, self.scope = db, scope

    def __getattr__(self, method):
        def call(*args, **kwargs):
            with self.db.session(self.scope) as session:
                return getattr(ApplicationRunRepository(session), method)(*args, **kwargs)

        return call


class ExplanationsRepository:
    """Questions about a calculated run and the answers the explanation workflow gave."""

    def __init__(self, session):
        from msa.db.models import tables_for

        self.session = session
        self.table = tables_for(session)["run_explanation"]

    def create(self, explanation_id, run_id, question, *, created_by):
        from msa.db.base import utcnow

        from .common import require_text

        require_text(question, "question")
        require_text(created_by, "created_by")
        now = utcnow()
        self.session.execute(
            self.table.insert().values(
                explanation_id=explanation_id,
                run_id=run_id,
                question=question,
                status="queued",
                answer=None,
                error=None,
                created_by=created_by,
                created_at=now,
                updated_at=now,
            )
        )
        return self.get(explanation_id)

    def update(self, explanation_id, *, status, answer=None, error=None):
        from sqlalchemy import update

        from msa.db.base import utcnow

        self.session.execute(
            update(self.table)
            .where(self.table.c.explanation_id == explanation_id)
            .values(
                status=status,
                answer=None if answer is None else json_payload(answer),
                error=error,
                updated_at=utcnow(),
            )
        )

    def get(self, explanation_id):
        from sqlalchemy import select

        row = (
            self.session.execute(
                select(self.table).where(self.table.c.explanation_id == explanation_id)
            )
            .mappings()
            .first()
        )
        if row is None:
            raise KeyError(explanation_id)
        return dict(row)

    def for_run(self, run_id):
        from sqlalchemy import select

        return [
            dict(row)
            for row in self.session.execute(
                select(self.table)
                .where(self.table.c.run_id == run_id)
                .order_by(self.table.c.created_at, self.table.c.explanation_id)
            ).mappings()
        ]
