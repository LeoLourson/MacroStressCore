"""The catalogs of the platform: instrument types, models, factors, slices, workflows.

The browser app, the report and the MCP tools read the same declarations the plugins make;
none of this carries portfolio data, so it is open to anyone who can reach the API.
"""

from fastapi import APIRouter

from msa.platform.catalog import asset_types, factors, models, slices, workflows
from msa.platform.docs import documentation

router = APIRouter(tags=["catalog"])


@router.get("/v1/asset-types")
def asset_types_catalog():
    """Every registered instrument type: its schemas, editor, models, metrics and views."""
    return asset_types()


@router.get("/v1/models")
def models_catalog():
    """Every registered calculation model: types, metrics with units, slices, limits."""
    return models()


@router.get("/v1/factors")
def factors_catalog():
    """Risk factors a scenario may move: unit, scope, how a shock applies, time structure."""
    return factors()


@router.get("/v1/slices")
def slices_catalog():
    """Portfolio slices: what each adds up and on which coverage basis."""
    return slices()


@router.get("/v1/workflows")
def workflows_catalog():
    """Workflows with their stages, nodes, extension points and the agents that join them."""
    return workflows()


@router.get("/v1/docs")
def docs_catalog():
    """The mathematics: the platform's pages, then the pages each plugin carries."""
    return documentation()
