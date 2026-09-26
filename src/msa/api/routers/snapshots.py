"""Data snapshots of both namespaces: import once, read many times, never change."""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder

from msa.contracts.snapshot import DataSnapshot
from msa.db.repositories.snapshots import SnapshotConflict, SnapshotsRepository

from ..auth import require_role
from ..dependencies import Authenticated, access
from ..problem import Problem

router = APIRouter(tags=["snapshots"])


@router.get("/v1/snapshots")
@router.get("/v1/demo/snapshots")
def snapshots(request: Request, principal: Authenticated):
    scope = access(request, principal)
    with request.app.state.db.session(scope) as session:
        return jsonable_encoder(SnapshotsRepository(session).list())


@router.post("/v1/snapshots", status_code=201)
@router.post("/v1/demo/snapshots", status_code=201)
def import_snapshot(payload: DataSnapshot, request: Request, principal: Authenticated):
    """Quotes, exchange rates, statements and assumptions, each with its date and sources.

    An item dated after the snapshot's own date is refused; the same id with other content
    is refused, so a run's recorded snapshot always means the numbers it read.
    """
    scope = access(request, principal, "write")
    require_role(principal, *(["analyst", "demo"] if scope == "demo" else []))
    with request.app.state.db.session(scope) as session:
        try:
            row = SnapshotsRepository(session).save(payload, created_by=principal.actor)
        except SnapshotConflict as exc:
            raise Problem(409, str(exc)) from exc
    request.app.state.db.audit(
        scope,
        principal.actor,
        "snapshot.imported",
        details={"snapshot_id": payload.snapshot_id, "sha256": row["sha256"]},
    )
    return jsonable_encoder(row)


@router.get("/v1/snapshots/{snapshot_id}")
@router.get("/v1/demo/snapshots/{snapshot_id}")
def snapshot(
    snapshot_id: str,
    request: Request,
    principal: Authenticated,
    kind: Annotated[str | None, Query()] = None,
    subject: Annotated[str | None, Query()] = None,
):
    """The snapshot's header and items, optionally one kind or one subject."""
    scope = access(request, principal)
    with request.app.state.db.session(scope) as session:
        repository = SnapshotsRepository(session)
        header = repository.header(snapshot_id)
        items = repository.items(
            snapshot_id, kind=kind, subjects=[subject] if subject is not None else None
        )
    return jsonable_encoder({**header, "items": [item.model_dump(mode="json") for item in items]})
