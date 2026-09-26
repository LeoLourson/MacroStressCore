import math
import time

from sqlalchemy import select, update

from msa.db.models import tables_for
from msa.db.repositories.common import insert_once

from .problem import Problem


class RateLimiter:
    def __init__(self, db, *, run_limit=60, agent_limit=600, concurrent_limit=5, clock=time.time):
        self.db = db
        self.limits = {"run": run_limit, "agent": agent_limit}
        self.concurrent_limit, self.clock = concurrent_limit, clock

    def reserve(self, scope, principal, kind, *, tokens=(), count=None):
        now = self.clock()
        with self.db.session(scope) as session:
            table = tables_for(session)["api_quota"]
            insert_once(session, table, {"principal": principal, "history": [], "active": []})
            row = (
                session.execute(
                    select(table).where(table.c.principal == principal).with_for_update()
                )
                .mappings()
                .one()
            )
            history = [h for h in row["history"] if h[1] > now - 3600]
            same = [h for h in history if h[0] == kind]
            count = max(1, len(tokens)) if count is None else count
            if len(same) + count > self.limits[kind]:
                retry = max(1, math.ceil(same[0][1] + 3600 - now)) if same else 3600
                raise Problem(429, "Hourly quota exceeded", headers={"Retry-After": str(retry)})
            active = row["active"]
            if set(tokens) & set(active):
                raise Problem(409, "Run is already executing")
            if len(active) + len(tokens) > self.concurrent_limit:
                raise Problem(429, "Concurrent run quota exceeded", headers={"Retry-After": "1"})
            session.execute(
                update(table)
                .where(table.c.principal == principal)
                .values(history=history + [[kind, now]] * count, active=active + list(tokens))
            )

    def release(self, scope, principal, token):
        with self.db.session(scope) as session:
            table = tables_for(session)["api_quota"]
            row = (
                session.execute(
                    select(table).where(table.c.principal == principal).with_for_update()
                )
                .mappings()
                .first()
            )
            if row is not None:
                session.execute(
                    update(table)
                    .where(table.c.principal == principal)
                    .values(active=[t for t in row["active"] if t != token])
                )

    def reconcile(self, scope):
        """Remove reservations orphaned by a crash, before the single worker recovers jobs."""
        with self.db.session(scope) as session:
            tables = tables_for(session)
            jobs, table = tables["api_job"], tables["api_quota"]
            active_ids = set(
                session.scalars(
                    select(jobs.c.job_id).where(jobs.c.status.in_({"queued", "running"}))
                )
            )
            for row in session.execute(select(table).with_for_update()).mappings():
                session.execute(
                    update(table)
                    .where(table.c.principal == row["principal"])
                    .values(active=[token for token in row["active"] if token in active_ids])
                )
