"""Load the demo catalog into the isolated demo schema.

The data snapshots go first, then the portfolios that read them (the bundle format), then
the event library (demo/events). Portfolios and snapshots are assembled by
``demo.catalog``: the headers in demo/portfolios and demo/snapshots, the positions and data
from each plugin's ``demo_data``. Built-in portfolios and events the catalog no longer has
are removed; the historical pilot event (``demo.pilot``) stays.
"""

import argparse
import json
import os
from pathlib import Path

from demo import catalog as demo_catalog
from demo.pilot import EVENT_ID as PILOT_EVENT_ID
from msa.db.repositories.demo import DemoRepository
from msa.db.session import engine, session_scope
from msa.platform.registry import registry

CATALOG = Path(__file__).resolve().parent


def seed_demo(bind, catalog=CATALOG):
    with session_scope(bind, scope="demo", scopes={"demo:*"}) as session:
        repository = DemoRepository(session)
        counts = {}
        for snapshot_id in demo_catalog.snapshot_ids(root=catalog):
            snapshot = demo_catalog.snapshot(snapshot_id, root=catalog)
            repository.seed_snapshot(snapshot)
            counts[snapshot.snapshot_id] = len(snapshot.items)
        for portfolio_id in demo_catalog.portfolio_ids(root=catalog):
            bundle = demo_catalog.bundle(portfolio_id, root=catalog)
            repository.seed_portfolio(bundle, registry=registry())
            counts[bundle.portfolio.portfolio_id] = len(bundle.positions)
        events = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((catalog / "events").glob("*.json"))
        ]
        for event in events:
            repository.seed_event(event)
        repository.retire(
            demo_catalog.portfolio_ids(root=catalog),
            [event["event_id"] for event in events] + [PILOT_EVENT_ID],
        )
        return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("MSA_DEMO_DATABASE_URL") or os.environ.get("MSA_DATABASE_URL"),
    )
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    args = parser.parse_args()
    bind = engine(args.database_url)
    try:
        print(json.dumps(seed_demo(bind, args.catalog), ensure_ascii=False))
    finally:
        bind.dispose()


if __name__ == "__main__":
    main()
