"""Portfolios of both namespaces: parties, instruments and positions; the analyst's editor."""

from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder

from msa.contracts.domain import PortfolioBundle
from msa.db.repositories.demo import DemoRepository
from msa.db.repositories.portfolios import PortfolioProblem, PortfoliosRepository
from msa.platform.registry import registry

from ..auth import require_role
from ..dependencies import Authenticated, access
from ..portfolio_draft import PortfolioDraft, build
from ..problem import Problem

router = APIRouter(tags=["portfolios"])


@router.get("/v1/portfolios")
@router.get("/v1/demo/portfolios")
def portfolios(request: Request, principal: Authenticated):
    scope = access(request, principal)
    with request.app.state.db.session(scope) as session:
        return jsonable_encoder(PortfoliosRepository(session).list_portfolios())


@router.get("/v1/portfolios/{portfolio_id}")
@router.get("/v1/demo/portfolios/{portfolio_id}")
def portfolio(portfolio_id: str, request: Request, principal: Authenticated):
    """The portfolio with every party, instrument and position it refers to."""
    scope = access(request, principal)
    return request.app.state.agents.bundle(scope, portfolio_id).model_dump(mode="json")


@router.get("/v1/portfolios/{portfolio_id}/names")
@router.get("/v1/demo/portfolios/{portfolio_id}/names")
def names(portfolio_id: str, request: Request, principal: Authenticated):
    """What a person calls each position: its issuer, else its instrument."""
    return request.app.state.agents.names(access(request, principal), portfolio_id)


@router.post("/v1/portfolios", status_code=201)
@router.post("/v1/demo/portfolios", status_code=201)
def import_bundle(payload: PortfolioBundle, request: Request, principal: Authenticated):
    """Import a portfolio as a bundle; terms and parameters are checked by their plugins."""
    scope = access(request, principal, "write")
    require_role(principal, *(["analyst", "demo"] if scope == "demo" else []))
    payload.portfolio.builtin = False
    with request.app.state.db.session(scope) as session:
        try:
            PortfoliosRepository(session).save_bundle(payload, registry=registry())
        except PortfolioProblem as exc:
            raise Problem(
                422,
                "Portfolio does not satisfy its plugins' schemas",
                violations=[{"rule_id": "V2", "path": "", "message": m} for m in exc.problems],
            ) from exc
    request.app.state.db.audit(
        scope,
        principal.actor,
        "portfolio.imported",
        details={"portfolio_id": payload.portfolio.portfolio_id},
    )
    return {"portfolio_id": payload.portfolio.portfolio_id}


@router.post("/v1/demo/portfolios/draft", status_code=201)
def draft(payload: PortfolioDraft, request: Request, principal: Authenticated):
    """A portfolio typed in the editor; each number becomes the analyst's sourced assumption."""
    scope = access(request, principal, "write")
    today = date.today()
    portfolio_id = f"UPLOAD-{uuid4()}"
    try:
        bundle, snapshot = build(
            payload,
            author=principal.actor,
            today=today,
            registry=registry(),
            portfolio_id=portfolio_id,
        )
    except ValueError as exc:
        raise Problem(422, str(exc)) from exc
    with request.app.state.db.session(scope) as session:
        try:
            saved = DemoRepository(session).save_upload(
                bundle, snapshot, registry=registry(), author=principal.actor
            )
        except PortfolioProblem as exc:
            raise Problem(422, "; ".join(exc.problems)) from exc
    return jsonable_encoder(saved)


@router.delete("/v1/demo/portfolios/{portfolio_id}", status_code=204)
def delete(portfolio_id: str, request: Request, principal: Authenticated):
    scope = access(request, principal, "write")
    with request.app.state.db.session(scope) as session:
        DemoRepository(session).delete_portfolio(portfolio_id)
