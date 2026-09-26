from fastapi import APIRouter, Request

from msa.agents.causal_output import reachable_factors, scenario_violations, sector_effects
from msa.validators import validate

from ..dependencies import Authenticated, access
from ..schemas import IngestRequest, ScenarioCheckRequest

router = APIRouter(tags=["documents"])


@router.post("/v1/documents", status_code=201)
@router.post("/v1/demo/documents", status_code=201)
def ingest(payload: IngestRequest, request: Request, principal: Authenticated):
    """The event document of a run, parsed into addressable fragments; runs cite its doc_id."""
    scope = access(request, principal, "run")
    request.app.state.limiter.reserve(scope, principal.key_id, "agent")
    document = request.app.state.agents.ingest(scope, payload)
    request.app.state.db.audit(
        scope, principal.actor, "document.ingested", details={"doc_id": document.doc_id}
    )
    return document.model_dump(mode="json")


@router.post("/v1/scenario-check")
@router.post("/v1/demo/scenario-check")
def scenario_check(payload: ScenarioCheckRequest, request: Request, principal: Authenticated):
    """What the graph stop would say about a draft, plus the scenario's effect on sectors.

    The draft is checked the way resume checks it, so the analyst does not meet a refusal
    after pressing confirm.
    """
    scope = access(request, principal, "run")
    request.app.state.limiter.reserve(scope, principal.key_id, "agent")
    graph, parameters = payload.graph, payload.macro_parameters
    verdicts = [v.model_dump(mode="json") for v in validate("TransmissionGraph", graph) if not v.ok]
    channels = [
        node.get("id")
        for node in graph.get("nodes") or []
        if isinstance(node, dict) and node.get("kind") == "channel"
    ]
    coverage = []
    if payload.run_id:
        request.app.state.runs.status(scope, payload.run_id)
        job = request.app.state.runs.job(scope, payload.run_id)
        coverage = request.app.state.runs.scenario_coverage(
            scope, job["payload"], graph, parameters
        )
    return {
        "violations": verdicts
        + scenario_violations(parameters, graph, required=payload.required)
        + coverage,
        "effects": sector_effects(graph, parameters),
        "factors": {channel: reachable_factors(graph, channel) for channel in channels},
    }
