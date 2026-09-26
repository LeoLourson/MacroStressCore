"""Data snapshots: imported once, read by runs, never changed.

A snapshot is written whole or not at all. Re-importing the same content under the same id
is a no-op; different content under an existing id is refused, so a run's recorded
snapshot always means the numbers it read.
"""

from sqlalchemy import delete, or_, select

from msa.contracts.snapshot import DataSnapshot, SnapshotItem, content_hash
from msa.db.base import utcnow
from msa.db.models import tables_for

from .common import require_text


class SnapshotConflict(ValueError):
    pass


class SnapshotsRepository:
    def __init__(self, session):
        self.session = session
        self.tables = tables_for(session)

    def save(self, snapshot: DataSnapshot, *, created_by: str, expires_at=None) -> dict:
        snapshot = DataSnapshot.model_validate(snapshot)
        require_text(created_by, "created_by")
        digest = content_hash(snapshot)
        table = self.tables["data_snapshot"]
        existing = (
            self.session.execute(select(table).where(table.c.snapshot_id == snapshot.snapshot_id))
            .mappings()
            .first()
        )
        if existing is not None:
            if existing["sha256"] != digest:
                raise SnapshotConflict(
                    f"snapshot {snapshot.snapshot_id} already exists with other content"
                )
            return dict(existing)
        row = {
            "snapshot_id": snapshot.snapshot_id,
            "as_of": snapshot.as_of,
            "label": snapshot.label,
            "kind": snapshot.kind,
            "sha256": digest,
            "created_by": created_by,
            "created_at": utcnow(),
            "expires_at": expires_at,
            "metadata": snapshot.metadata,
        }
        self.session.execute(table.insert().values(**row))
        items = self.tables["snapshot_item"]
        for item in snapshot.items:
            data = item.model_dump(mode="json")
            data["observed_on"] = item.observed_on
            self.session.execute(items.insert().values(snapshot_id=snapshot.snapshot_id, **data))
        return row

    def exists(self, snapshot_id) -> bool:
        table = self.tables["data_snapshot"]
        return (
            self.session.execute(
                select(table.c.snapshot_id).where(table.c.snapshot_id == snapshot_id)
            ).first()
            is not None
        )

    def header(self, snapshot_id) -> dict:
        table = self.tables["data_snapshot"]
        row = (
            self.session.execute(select(table).where(table.c.snapshot_id == snapshot_id))
            .mappings()
            .first()
        )
        if row is None:
            raise KeyError(snapshot_id)
        return dict(row)

    def items(self, snapshot_id, *, kind=None, subjects=None) -> list[SnapshotItem]:
        table = self.tables["snapshot_item"]
        query = select(table).where(table.c.snapshot_id == snapshot_id)
        if kind is not None:
            query = query.where(table.c.kind == kind)
        if subjects is not None:
            query = query.where(table.c.subject.in_(list(subjects)))
        return [
            SnapshotItem.model_validate({k: v for k, v in dict(r).items() if k != "snapshot_id"})
            for r in self.session.execute(query.order_by(table.c.item_id)).mappings()
        ]

    def get(self, snapshot_id) -> DataSnapshot:
        header = self.header(snapshot_id)
        return DataSnapshot(
            snapshot_id=snapshot_id,
            as_of=header["as_of"],
            label=header["label"],
            kind=header["kind"],
            items=self.items(snapshot_id),
            metadata=header["metadata"] or {},
        )

    def list(self, *, now=None) -> list[dict]:
        table = self.tables["data_snapshot"]
        items = self.tables["snapshot_item"]
        rows = self.session.execute(
            select(table)
            .where(or_(table.c.expires_at.is_(None), table.c.expires_at > (now or utcnow())))
            .order_by(table.c.as_of.desc(), table.c.snapshot_id)
        ).mappings()
        result = []
        for row in rows:
            count = len(
                self.session.execute(
                    select(items.c.item_id).where(items.c.snapshot_id == row["snapshot_id"])
                ).all()
            )
            result.append({**dict(row), "items": count})
        return result

    def delete(self, snapshot_id):
        for name in ("snapshot_item", "data_snapshot"):
            table = self.tables[name]
            self.session.execute(delete(table).where(table.c.snapshot_id == snapshot_id))
