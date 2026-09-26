from uuid import uuid4

from sqlalchemy import insert, select

from msa.db.models import tables_for
from msa.db.repositories.common import require_text
from msa.db.repositories.runs import json_payload


class AuditLog:
    def __init__(self, session):
        self.session = session
        self.table = tables_for(session)["audit_log"]

    def log(
        self,
        actor,
        action,
        run_id=None,
        node=None,
        attempt=None,
        tool=None,
        standalone=False,
        *,
        details=None,
    ):
        require_text(actor, "actor")
        require_text(action, "action")
        if standalone and run_id is not None:
            raise ValueError("Standalone actions must not belong to a run")
        if attempt is not None and (type(attempt) is not int or attempt < 1):
            raise ValueError("attempt must be a positive integer")
        if tool and (not node or attempt is None or (not standalone and not run_id)):
            raise ValueError("Tool calls require node, attempt and run_id (unless standalone)")
        audit_id = str(uuid4())
        self.session.execute(
            insert(self.table).values(
                audit_id=audit_id,
                actor=actor,
                action=action,
                run_id=run_id,
                node=node,
                attempt=attempt,
                tool=tool,
                standalone=standalone,
                details=json_payload(details or {}),
            )
        )
        return audit_id

    def for_run(self, run_id):
        return list(
            self.session.execute(
                select(self.table)
                .where(self.table.c.run_id == run_id)
                .order_by(self.table.c.occurred_at, self.table.c.audit_id)
            ).mappings()
        )
