"""The demo namespace's event library."""

from fastapi import APIRouter, Request

from ..dependencies import Authenticated, access

router = APIRouter(prefix="/v1/demo", tags=["demo"])


@router.get("/events")
def events(request: Request, principal: Authenticated):
    scope = access(request, principal)
    return [dict(row) for row in request.app.state.agents.events(scope)]
