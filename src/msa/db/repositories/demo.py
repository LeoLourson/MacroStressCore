"""The demo catalog: built-in portfolios, the demo snapshot and events, and analysts'
portfolios kept for seven days together with the snapshot of the numbers they typed."""

from datetime import timedelta
from hashlib import sha256

from sqlalchemy import select

from msa.contracts.domain import PortfolioBundle
from msa.contracts.snapshot import DataSnapshot
from msa.db.base import utcnow
from msa.db.models import tables_for

from .common import upsert
from .portfolios import PortfoliosRepository
from .snapshots import SnapshotsRepository

UPLOAD_DAYS = 7


class DemoRepository:
    def __init__(self, session):
        if session.info.get("data_scope") != "demo":
            raise PermissionError("DemoRepository requires a demo-scoped session")
        self.session = session
        self.tables = tables_for(session)
        self.portfolios = PortfoliosRepository(session)
        self.snapshots = SnapshotsRepository(session)

    def seed_snapshot(self, snapshot: DataSnapshot):
        return self.snapshots.save(snapshot, created_by="demo:catalog")

    def seed_portfolio(self, bundle: PortfolioBundle, *, registry):
        bundle = PortfolioBundle.model_validate(bundle)
        bundle.portfolio.builtin = True
        self.portfolios.save_bundle(bundle, registry=registry)

    def save_upload(self, bundle: PortfolioBundle, snapshot: DataSnapshot, *, registry, author):
        """An analyst's portfolio and its own snapshot: kept for seven days, then gone."""
        if not 1 <= len(bundle.positions) <= 100:
            raise ValueError("Portfolio must contain 1 to 100 positions")
        expires_at = utcnow() + timedelta(days=UPLOAD_DAYS)
        self.snapshots.save(snapshot, created_by=author, expires_at=expires_at)
        self.portfolios.save_bundle(bundle, registry=registry, owned=True, expires_at=expires_at)
        return {"portfolio_id": bundle.portfolio.portfolio_id, "expires_at": expires_at}

    def delete_portfolio(self, portfolio_id):
        row = self.portfolios._portfolio(portfolio_id, include_expired=True)
        self.portfolios.delete_portfolio(portfolio_id)
        snapshot_id = row["snapshot_id"]
        if snapshot_id:
            header = self.snapshots.header(snapshot_id)
            # An analyst's snapshot belongs to their portfolio; the demo snapshot stays.
            if header["kind"] == "analyst":
                self.snapshots.delete(snapshot_id)

    def seed_event(self, event):
        values = {key: event[key] for key in ("event_id", "title", "text", "metadata")}
        values["sha256"] = sha256(event["text"].encode("utf-8")).hexdigest()
        upsert(self.session, self.tables["event"], values)

    def events(self):
        table = self.tables["event"]
        return list(self.session.execute(select(table).order_by(table.c.event_id)).mappings())
