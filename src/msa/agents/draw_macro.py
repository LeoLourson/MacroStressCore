"""Draw Macro (TZ 3.4): one scenario set for the whole run, fixed before any calculation.

The set is the confirmed scenario's factor distributions plus the subject-specific shocks
the positions' models declared (an equity's residual return). The matrix is deterministic
in (parameters, seed, points), so every position branch regenerates exactly the same
realisations; this node records its specification, its hash and the scenario set's
identity, and V11 checks every branch against them.
"""

from datetime import date

from pydantic import BaseModel, Field

from msa.contracts.common import McPoints, Seed, Sha256
from msa.contracts.graph import TransmissionGraph
from msa.contracts.scenario import MacroParameter
from msa.engine.runner import factor_versions
from msa.engine.scenario_set import Realisations, scenario_set_from_parameters
from msa.plugin_sdk.model import IdiosyncraticFactor

from .base import AgentError

REPLICATES = 8


class DrawInput(BaseModel):
    graph: dict | None = None
    seed: Seed
    mc_points: McPoints
    as_of: date
    horizon: int = Field(ge=1, le=360)
    # The scenario confirmed by the analyst.
    parameters: dict[str, MacroParameter] = {}
    idiosyncratic: list[IdiosyncraticFactor] = []


class ScenarioDraws(BaseModel):
    """What the run records about its scenario set: specification, sizes and hashes."""

    seed: Seed
    replicates: int = Field(ge=8)
    points: int = Field(ge=1)
    names: list[str]
    sha256: Sha256
    spec: dict
    scenario_id: Sha256
    factor_versions: dict[str, str] = {}


class DrawMacroAgent:
    """Draws only from the scenario the analyst confirmed."""

    def __init__(self, *, registry):
        self.registry = registry

    def run(self, payload: DrawInput) -> ScenarioDraws:
        if not payload.parameters:
            raise AgentError("A confirmed scenario is required")
        points = payload.mc_points // REPLICATES
        scenario_set = scenario_set_from_parameters(
            payload.parameters, points=points, replicates=REPLICATES
        ).with_idiosyncratic(payload.idiosyncratic)
        versions = factor_versions(self.registry, scenario_set)
        view = Realisations(
            scenario_set=scenario_set,
            seed=payload.seed,
            as_of=payload.as_of,
            horizon=payload.horizon,
            graph=TransmissionGraph.model_validate(payload.graph) if payload.graph else None,
            factor_versions=versions,
        )
        return ScenarioDraws(
            seed=payload.seed,
            replicates=REPLICATES,
            points=points,
            names=list(view.sampled.names),
            sha256=view.macro_draws_sha256,
            spec=scenario_set.spec(),
            scenario_id=view.scenario_id,
            factor_versions=versions,
        )
