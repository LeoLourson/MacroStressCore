"""Load a portfolio bundle and, optionally, its data snapshot into one namespace.

The working (production) namespace has no other loader: its portfolios come from the bank's
systems in the bundle format of demo/portfolios/*.json (portfolio, parties, instruments,
positions), its data in the snapshot format of demo/snapshots/*.json, never through the
demo editor. Instrument terms and position parameters are checked against their plugins'
schemas before anything is written.

    uv run --frozen python ops/load_portfolio.py --scope production bank-portfolio.json \
        --snapshot bank-2026-09-30.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from msa.contracts import DataSnapshot, PortfolioBundle  # noqa: E402
from msa.db.repositories.portfolios import PortfoliosRepository  # noqa: E402
from msa.db.repositories.snapshots import SnapshotsRepository  # noqa: E402
from msa.db.session import engine, session_scope  # noqa: E402
from msa.platform.registry import registry  # noqa: E402


def load_portfolio(bind, bundle, scope="production", *, snapshot=None, actor="ops:loader"):
    bundle = PortfolioBundle.model_validate(bundle)
    with session_scope(bind, scope=scope, scopes={f"{scope}:*"}) as session:
        if snapshot is not None:
            SnapshotsRepository(session).save(
                DataSnapshot.model_validate(snapshot), created_by=actor
            )
        PortfoliosRepository(session).save_bundle(bundle, registry=registry())
        return len(bundle.positions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--scope", choices=("production", "demo"), default="production")
    parser.add_argument("--database-url", default=os.environ.get("MSA_DATABASE_URL"))
    args = parser.parse_args()
    bundle = json.loads(args.file.read_text(encoding="utf-8"))
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8")) if args.snapshot else None
    bind = engine(args.database_url)
    try:
        count = load_portfolio(bind, bundle, args.scope, snapshot=snapshot)
    finally:
        bind.dispose()
    loaded = {
        "portfolio_id": bundle["portfolio"]["portfolio_id"],
        "positions": count,
        "snapshot_id": (snapshot or {}).get("snapshot_id"),
        "scope": args.scope,
    }
    print(json.dumps(loaded))


if __name__ == "__main__":
    main()
