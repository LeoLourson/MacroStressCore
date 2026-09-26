"""Load the sole demo data source (this directory) into the isolated demo schema.

The data snapshots go first (demo/snapshots), then the portfolios that read them
(demo/portfolios, the bundle format), then the event library (demo/events).
"""

import argparse
import json
import os
from pathlib import Path

from msa.contracts import DataSnapshot, PortfolioBundle
from msa.db.repositories.demo import DemoRepository
from msa.db.session import engine, session_scope
from msa.platform.registry import registry

CATALOG = Path(__file__).resolve().parent


def seed_demo(bind, catalog=CATALOG):
    with session_scope(bind, scope="demo", scopes={"demo:*"}) as session:
        repository = DemoRepository(session)
        counts = {}
        for path in sorted((catalog / "snapshots").glob("*.json")):
            snapshot = DataSnapshot.model_validate(json.loads(path.read_text(encoding="utf-8")))
            repository.seed_snapshot(snapshot)
            counts[snapshot.snapshot_id] = len(snapshot.items)
        for path in sorted((catalog / "portfolios").glob("DEMO-*.json")):
            bundle = PortfolioBundle.model_validate(json.loads(path.read_text(encoding="utf-8")))
            repository.seed_portfolio(bundle, registry=registry())
            counts[bundle.portfolio.portfolio_id] = len(bundle.positions)
        for path in sorted((catalog / "events").glob("EVENT-*.json")):
            repository.seed_event(json.loads(path.read_text(encoding="utf-8")))
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
