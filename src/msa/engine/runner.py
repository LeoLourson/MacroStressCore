"""The calculation of a set of positions on one scenario set, without any orchestration.

This is what a run does between the confirmed scenario and the portfolio: prepare every
position against the snapshot, draw the joint realisations once (including the
subject-specific shocks the models declared), calculate every position on them and keep
each contribution's realisations for the aggregator. The run graph performs the same steps
as separate, journaled nodes; tests, the conformance check and the demo run call this.
"""

from dataclasses import dataclass, field

from msa.contracts.domain import PositionContext
from msa.contracts.result import CalculationResult
from msa.contracts.snapshot import DataSnapshot
from msa.platform.registry import Registry
from msa.plugin_sdk.model import CalculationContext, Diagnostics, PreparedInputs, RunOptions

from .dispatch import calculate, not_run, prepare
from .scenario_set import Realisations, ScenarioSet, scenario_set_from_parameters
from .snapshot import SnapshotIndex


@dataclass
class Batch:
    results: list[CalculationResult]
    #: (position id, slice id) -> loss realisations in the shared order.
    draws: dict[tuple[str, str], list[float]]
    #: position id -> slice id -> exposure on the slice's basis.
    exposures: dict[str, dict[str, float | None]]
    realisations: Realisations
    prepared: dict[str, PreparedInputs] = field(default_factory=dict)
    diagnostics: dict[str, Diagnostics] = field(default_factory=dict)


def idiosyncratic_shocks(diagnostics) -> list:
    """Every subject-specific shock the models declared; one spec per name."""
    shocks = {}
    for item in diagnostics:
        for shock in item.idiosyncratic:
            known = shocks.get(shock.name)
            if known is not None and known != shock:
                raise ValueError(f"two different specifications of shock {shock.name}")
            shocks[shock.name] = shock
    return [shocks[name] for name in sorted(shocks)]


def factor_versions(registry: Registry, scenario_set: ScenarioSet) -> dict[str, str]:
    versions = {}
    for parameter in scenario_set.parameters.values():
        if parameter.factor and parameter.factor in registry.factors:
            versions[parameter.factor] = registry.plugin_of(parameter.factor).version
    return versions


def split_draws(result: CalculationResult) -> tuple[CalculationResult, dict[str, list[float]]]:
    """The result as it is stored, and its contributions' realisations kept apart."""
    draws = {c.slice_id: list(c.draws) for c in result.contributions if c.draws is not None}
    return result, draws


def run_batch(
    contexts: list[PositionContext],
    snapshot: DataSnapshot,
    parameters: dict,
    graph,
    *,
    as_of,
    horizon: int,
    seed: int,
    registry: Registry,
    sector_of,
    points: int = 1024,
    replicates: int = 8,
    options: dict | None = None,
    run_id: str | None = None,
) -> Batch:
    base_currency = contexts[0].base_currency if contexts else "RUB"
    run_options = RunOptions(
        as_of=as_of, horizon=horizon, base_currency=base_currency, options=options or {}
    )
    index = SnapshotIndex(snapshot.snapshot_id, snapshot.items)
    prepared, diagnostics = {}, {}
    for context in contexts:
        item, found = prepare(context, run_options, index, registry, sector_of=sector_of)
        prepared[context.position_id] = item
        diagnostics[context.position_id] = found
    scenario_set = scenario_set_from_parameters(
        parameters, points=points, replicates=replicates
    ).with_idiosyncratic(idiosyncratic_shocks(diagnostics.values()))
    realisations = Realisations(
        scenario_set=scenario_set,
        seed=seed,
        as_of=as_of,
        horizon=horizon,
        graph=graph,
        factor_versions=factor_versions(registry, scenario_set),
    )
    calculation = CalculationContext(
        as_of=as_of,
        horizon=horizon,
        seed=seed,
        base_currency=base_currency,
        scenario=realisations,
        snapshot_id=snapshot.snapshot_id,
        scenario_set=scenario_set,
        options=options or {},
        run_id=run_id,
    )
    results, draws, exposures = [], {}, {}
    for context in contexts:
        position_id = context.position_id
        exposures[position_id] = dict(diagnostics[position_id].exposures)
        if prepared[position_id] is None:
            result = not_run(
                context,
                diagnostics[position_id],
                registry,
                as_of=as_of,
                horizon=horizon,
                seed=seed,
                scenario_id=realisations.scenario_id,
                snapshot_id=snapshot.snapshot_id,
                macro_draws_sha256=realisations.macro_draws_sha256,
            )
        else:
            result = calculate(
                prepared[position_id], diagnostics[position_id], calculation, registry
            )
        result, own = split_draws(result)
        for slice_id, values in own.items():
            draws[position_id, slice_id] = values
        results.append(result)
    return Batch(
        results=results,
        draws=draws,
        exposures=exposures,
        realisations=realisations,
        prepared=prepared,
        diagnostics=diagnostics,
    )
