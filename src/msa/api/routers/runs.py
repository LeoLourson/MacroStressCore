from typing import Annotated

from fastapi import APIRouter, Query, Request

from msa.contracts import RunRequest

from ..auth import require_role
from ..dependencies import Authenticated, access
from ..schemas import ExplainRequest, ResumeRequest

router = APIRouter(tags=["runs"])


@router.get("/v1/me")
def me(request: Request, principal: Authenticated):
    """The caller's identity, so interfaces offer only the actions its role permits."""
    return {
        "actor": principal.actor,
        "role": principal.role,
        "scopes": sorted(principal.scopes),
        "expires_at": principal.expires_at,
        # An external LLM limits the screens to synthetic demo portfolios.
        "llm": request.app.state.agents.llm(),
    }


@router.get("/v1/runs")
@router.get("/v1/demo/runs")
def runs(
    request: Request,
    principal: Authenticated,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    return request.app.state.runs.list_runs(access(request, principal), limit)


@router.post("/v1/runs", status_code=202)
@router.post("/v1/demo/runs", status_code=202)
def start(payload: RunRequest, request: Request, principal: Authenticated):
    scope = access(request, principal, "run")
    require_role(principal, "analyst", *(["demo"] if scope == "demo" else []))
    return request.app.state.runs.submit(scope, payload, principal)


@router.get("/v1/runs/{run_id}")
@router.get("/v1/demo/runs/{run_id}")
def status(run_id: str, request: Request, principal: Authenticated):
    return request.app.state.runs.status(access(request, principal), run_id)


@router.get("/v1/runs/{run_id}/report")
@router.get("/v1/demo/runs/{run_id}/report")
def report(run_id: str, request: Request, principal: Authenticated):
    return request.app.state.runs.report(access(request, principal), run_id)


@router.get("/v1/runs/{run_id}/artifacts")
@router.get("/v1/demo/runs/{run_id}/artifacts")
def artifacts(run_id: str, request: Request, principal: Authenticated):
    return request.app.state.runs.artifacts(access(request, principal), run_id)


@router.get("/v1/runs/{run_id}/trace")
@router.get("/v1/demo/runs/{run_id}/trace")
def trace(run_id: str, request: Request, principal: Authenticated):
    """Where each number of the report comes from."""
    return request.app.state.runs.trace(access(request, principal), run_id)


@router.get("/v1/runs/{run_id}/activity")
@router.get("/v1/demo/runs/{run_id}/activity")
def activity(run_id: str, request: Request, principal: Authenticated):
    """LLM and MCP calls of the run: which model or tool, for which node, how long."""
    return request.app.state.runs.activity(access(request, principal), run_id)


@router.post("/v1/runs/{run_id}/resume", status_code=202)
@router.post("/v1/demo/runs/{run_id}/resume", status_code=202)
def resume(run_id: str, payload: ResumeRequest, request: Request, principal: Authenticated):
    scope = access(request, principal, "approve" if payload.approved is not None else "run")
    return request.app.state.runs.resume(scope, run_id, payload, principal)


@router.post("/v1/runs/{run_id}/explanations", status_code=202)
@router.post("/v1/demo/runs/{run_id}/explanations", status_code=202)
def explain(run_id: str, payload: ExplainRequest, request: Request, principal: Authenticated):
    """Ask about a calculated run; the answer comes from the run's own numbers."""
    scope = access(request, principal, "run")
    require_role(principal, "analyst", "risk_manager", *(["demo"] if scope == "demo" else []))
    return request.app.state.explanations.ask(scope, run_id, payload.question, principal)


@router.get("/v1/runs/{run_id}/explanations")
@router.get("/v1/demo/runs/{run_id}/explanations")
def explanations(run_id: str, request: Request, principal: Authenticated):
    return request.app.state.explanations.list(access(request, principal), run_id)


@router.get("/v1/runs/{run_id}/explanations/{explanation_id}")
@router.get("/v1/demo/runs/{run_id}/explanations/{explanation_id}")
def explanation(run_id: str, explanation_id: str, request: Request, principal: Authenticated):
    return request.app.state.explanations.get(access(request, principal), run_id, explanation_id)
