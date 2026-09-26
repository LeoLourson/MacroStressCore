import math

from sqlalchemy import insert, select

from msa.db.base import utc, utcnow
from msa.db.models import tables_for

from .common import require_text


class RuleThresholdsRepository:
    def __init__(self, session):
        self.session = session
        self.table = tables_for(session)["rule_threshold"]

    def as_of(self, ts):
        ts = utc(ts)
        rows = self.session.execute(
            select(self.table)
            .where(self.table.c.effective_at <= ts)
            .order_by(self.table.c.rule_id, self.table.c.revision.desc())
        ).mappings()
        result = {}
        for row in rows:
            result.setdefault(row["rule_id"], dict(row))
        return result

    def current(self):
        return self.as_of(utcnow())

    def history(self, rule_id):
        return list(
            self.session.execute(
                select(self.table)
                .where(self.table.c.rule_id == rule_id)
                .order_by(self.table.c.revision)
            ).mappings()
        )

    def change(self, rule_id, threshold, *, actor, reason, effective_at=None):
        from msa.db.audit import AuditLog

        require_text(actor, "actor")
        require_text(reason, "reason")
        if isinstance(threshold, bool) or not math.isfinite(threshold):
            raise ValueError("threshold must be finite")
        effective_at = utc(effective_at or utcnow())
        # Lock the stable first revision to serialize concurrent writers, even as history grows.
        first = (
            self.session.execute(
                select(self.table)
                .where(self.table.c.rule_id == rule_id, self.table.c.revision == 1)
                .with_for_update()
            )
            .mappings()
            .first()
        )
        if first is None:
            raise KeyError(rule_id)
        last = dict(self.history(rule_id)[-1])
        previous_at = last["effective_at"]
        if previous_at.tzinfo is None:  # SQLite stores UTC without tzinfo.
            from datetime import UTC

            previous_at = previous_at.replace(tzinfo=UTC)
        if effective_at <= previous_at:
            raise ValueError("History is append-only; effective_at must increase")
        if threshold < 0 or (last["unit"] == "fraction" and threshold > 1):
            raise ValueError("Threshold is outside the metric's range")
        if last["unit"] == "percentage_point" and threshold > 100:
            raise ValueError("Percentage-point threshold cannot exceed 100")
        updated = {
            **last,
            "threshold": threshold,
            "revision": last["revision"] + 1,
            "effective_at": effective_at,
            "changed_by": actor,
            "reason": reason,
        }
        self.session.execute(insert(self.table).values(**updated))
        AuditLog(self.session).log(
            actor,
            "rule_threshold.changed",
            details={
                "rule_id": rule_id,
                "revision": updated["revision"],
                "old_threshold": last["threshold"],
                "threshold": threshold,
                "reason": reason,
            },
        )
        return updated
