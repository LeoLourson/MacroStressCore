from datetime import date

from fastapi.encoders import jsonable_encoder

from msa.db.repositories.portfolios import PortfoliosRepository
from msa.db.repositories.snapshots import SnapshotsRepository
from msa.engine.snapshot import SnapshotIndex, resolve
from msa.plugin_sdk.model import DataRequirements

from ..audit import CallContext


def register(tool, services):
    @tool
    def resolve_inputs(
        portfolio_id: str,
        position_id: str,
        snapshot_id: str,
        as_of: date,
        requirements: dict,
        audit: CallContext,
    ) -> dict:
        """Resolve a position's data requirements against a snapshot, as of the valuation date.

        Reads only the snapshot items of the requested kinds; nothing dated after as_of is
        returned. No market or external source is contacted.
        """
        needs = DataRequirements.model_validate(requirements)
        with services.read_session() as session:
            bundle = PortfoliosRepository(session).get_bundle(portfolio_id)
            if position_id not in {p.position_id for p in bundle.positions}:
                raise KeyError(f"{position_id} is not a position of {portfolio_id}")
            kinds = sorted({item.kind for item in needs.data})
            snapshots = SnapshotsRepository(session)
            items = [item for kind in kinds for item in snapshots.items(snapshot_id, kind=kind)]
            sectors = PortfoliosRepository(session).sectors()
        data, missing = resolve(
            needs, SnapshotIndex(snapshot_id, items), as_of=as_of, sector_of=sectors.get
        )
        return jsonable_encoder(
            {
                "data": {
                    key: (
                        [item.model_dump(mode="json") for item in value]
                        if isinstance(value, list)
                        else (value.model_dump(mode="json") if value is not None else None)
                    )
                    for key, value in data.items()
                },
                "missing": missing,
            }
        )

    @tool
    def get_portfolio(portfolio_id: str, audit: CallContext) -> dict:
        """The portfolio with its parties, instruments and positions."""
        with services.read_session() as session:
            return PortfoliosRepository(session).get_bundle(portfolio_id).model_dump(mode="json")
