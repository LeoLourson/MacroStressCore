"""Aggregate (TZ 4.18, spec 16): the portfolio slices from joint realisations.

Losses are summed inside each shared realisation before any quantile is taken, slice by
slice; slices are never added to each other. Which results enter is decided by their
plugins (an approved inclusion rule admits a result that needs review, with disclosure).
"""

from datetime import date

from pydantic import BaseModel

from msa.contracts import CalculationResult, PortfolioResult
from msa.contracts.common import Sha256
from msa.engine.aggregation import aggregate_slices


class AggregateInput(BaseModel):
    run_id: str
    results: list[CalculationResult]
    #: position id -> slice id -> loss realisations in the shared order (never persisted).
    draws: dict[str, dict[str, list[float]]] = {}
    #: position id -> slice id -> exposure, for every position of the run.
    exposures: dict[str, dict[str, float | None]] = {}
    #: The same for every position of the portfolio, reached by the event or not.
    portfolio_exposures: dict[str, dict[str, float | None]] | None = None
    base_currency: str = "RUB"
    as_of: date
    horizon: int
    seed: int
    scenario_id: Sha256
    macro_draws_sha256: Sha256


class AggregateAgent:
    def __init__(self, *, registry):
        self.registry = registry

    def run(self, payload: AggregateInput) -> PortfolioResult:
        return aggregate_slices(
            payload.run_id,
            payload.results,
            draws={
                (position_id, slice_id): values
                for position_id, slices in payload.draws.items()
                for slice_id, values in slices.items()
            },
            exposures=payload.exposures,
            registry=self.registry,
            base_currency=payload.base_currency,
            as_of=payload.as_of,
            horizon=payload.horizon,
            seed=payload.seed,
            scenario_id=payload.scenario_id,
            macro_draws_sha256=payload.macro_draws_sha256,
            portfolio_exposures=payload.portfolio_exposures,
        )
