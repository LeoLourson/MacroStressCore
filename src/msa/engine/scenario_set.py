"""The approved scenario set and its joint realisations, shared by every position of a run.

The platform draws the realisations once, before any position is calculated, from the
confirmed factor distributions and the run seed: ``R`` independently scrambled Sobol
replicates of ``N`` points (spec 13), columns in the sorted order of parameter names.
Subject-specific shocks (an equity's residual return) and the uncertain elasticities of the
graph's edges are drawn by the platform too, each from its own deterministic stream keyed by
the run seed and the subject or edge, so they do not depend on which other positions the run
holds or in which order. These streams are stratified: every replicate covers the
distribution evenly, one point in each of ``N`` equal intervals, in a random order that makes
them independent of the scenario's Sobol points and of each other.

``scenario_id`` identifies the set: the factors and their order, the distributions, the
dependence, the dates, the draw sizes, the seed, the factor versions and the realised
values themselves.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256

import numpy as np
from scipy import stats

from msa.contracts.graph import TransmissionGraph
from msa.contracts.scenario import MacroParameter
from msa.plugin_sdk.model import IdiosyncraticFactor

from .scenarios import MIN_REPLICATES, Marginal, ScenarioDraws, draw

DEFAULT_POINTS = 8192
_EPS = 2.0**-53


@dataclass(frozen=True)
class ScenarioSet:
    """Confirmed factor distributions shared by all positions in one portfolio run."""

    parameters: dict[str, MacroParameter]
    points: int = DEFAULT_POINTS
    replicates: int = MIN_REPLICATES
    correlation: np.ndarray | None = None
    idiosyncratic: tuple[IdiosyncraticFactor, ...] = ()

    def __post_init__(self):
        if not self.parameters:
            raise ValueError("scenario_set requires at least one confirmed parameter")
        if self.points <= 0 or self.points & (self.points - 1):
            raise ValueError("points must be a power of two")
        if self.replicates < MIN_REPLICATES:
            raise ValueError(f"at least {MIN_REPLICATES} independent replicates are required")
        names = [item.name for item in self.idiosyncratic]
        if len(names) != len(set(names)):
            raise ValueError("idiosyncratic shocks must have unique names")
        if set(names) & set(self.parameters):
            raise ValueError("an idiosyncratic shock cannot share a scenario parameter's name")

    def marginals(self) -> dict[str, Marginal]:
        return {name: marginal(parameter) for name, parameter in self.parameters.items()}

    def sample(self, seed: int) -> ScenarioDraws:
        return draw(
            self.marginals(),
            seed,
            self.points,
            replicates=self.replicates,
            correlation=self.correlation,
        )

    def with_idiosyncratic(self, shocks) -> "ScenarioSet":
        unique = {item.name: item for item in shocks}
        return ScenarioSet(
            parameters=self.parameters,
            points=self.points,
            replicates=self.replicates,
            correlation=self.correlation,
            idiosyncratic=tuple(unique[name] for name in sorted(unique)),
        )

    def spec(self) -> dict:
        """The canonical, JSON-able description of the set (everything but the seed)."""
        return {
            "parameters": {
                name: parameter.model_dump(mode="json", exclude_none=True)
                for name, parameter in sorted(self.parameters.items())
            },
            "points": self.points,
            "replicates": self.replicates,
            "correlation": None if self.correlation is None else self.correlation.tolist(),
            "idiosyncratic": [item.model_dump(mode="json") for item in self.idiosyncratic],
        }

    @classmethod
    def from_spec(cls, spec: dict) -> "ScenarioSet":
        return cls(
            parameters={
                name: MacroParameter.model_validate(value)
                for name, value in spec["parameters"].items()
            },
            points=spec["points"],
            replicates=spec["replicates"],
            correlation=None
            if spec.get("correlation") is None
            else np.asarray(spec["correlation"], dtype=float),
            idiosyncratic=tuple(
                IdiosyncraticFactor.model_validate(item) for item in spec.get("idiosyncratic", [])
            ),
        )


def marginal(parameter: MacroParameter) -> Marginal:
    values = parameter.model_dump(exclude={"unit", "channel", "factor", "key"}, exclude_none=True)
    return Marginal(**values)


def scenario_set_from_parameters(
    parameters: dict[str, MacroParameter | dict],
    *,
    points: int = DEFAULT_POINTS,
    replicates: int = MIN_REPLICATES,
    correlation=None,
) -> ScenarioSet:
    """Build the scenario boundary from the scenario the analyst confirmed.

    A confirmed parameter may carry its label and sources; they describe it and do not
    enter the distribution.
    """
    parsed = {
        name: value
        if isinstance(value, MacroParameter)
        else MacroParameter.model_validate(
            {k: v for k, v in value.items() if k not in ("label", "evidence")}
        )
        for name, value in parameters.items()
    }
    return ScenarioSet(
        parameters=parsed,
        points=points,
        replicates=replicates,
        correlation=None if correlation is None else np.asarray(correlation, dtype=float),
    )


def stratified(key: str, points: int, replicates: int) -> np.ndarray:
    """Uniform draws ``(replicates, points)`` of one stream: each replicate puts one point in
    each of ``points`` equal intervals, in a random order, from ``default_rng([key, r])``."""
    stream = int.from_bytes(sha256(key.encode()).digest()[:8], "big")
    blocks = []
    for replicate in range(replicates):
        rng = np.random.default_rng([stream, replicate])
        blocks.append((rng.permutation(points) + rng.random(points)) / points)
    return np.stack(blocks)


def idiosyncratic_draws(shock: IdiosyncraticFactor, seed: int, points: int, replicates: int):
    """A subject's own shock, shaped ``(replicates, points)``, from its own stream."""
    unit = stratified(f"{seed}:{shock.subject}:{shock.name}", points, replicates)
    return stats.norm.ppf(np.clip(unit, _EPS, 1 - _EPS)) * shock.sigma


def edge_elasticities(graph, seed: int, points: int, replicates: int) -> dict:
    """``(src, dst)`` -> realisations ``(replicates, points)`` of each uncertain elasticity.

    A triangular, uniform or lognormal elasticity of an edge is drawn from the edge's own
    stream; a point elasticity has no realisations and the edge keeps its value.
    """
    result = {}
    for edge in TransmissionGraph.model_validate(graph).edges:
        spec = edge.elasticity
        if spec.family == "point":
            continue
        if spec.family == "lognormal":
            marginal_ = Marginal(kind="lognormal", mean=spec.mu, sigma=spec.sigma)
        else:
            marginal_ = Marginal(
                kind=spec.family,
                low=spec.low,
                mode=getattr(spec, "mode", None),
                high=spec.high,
            )
        unit = stratified(f"{seed}:edge:{edge.src}->{edge.dst}", points, replicates)
        result[(edge.src, edge.dst)] = marginal_.ppf(unit)
    return result


@dataclass
class Realisations:
    """The scenario set as models read it (``msa.plugin_sdk.ScenarioView``)."""

    scenario_set: ScenarioSet
    seed: int
    as_of: date
    horizon: int
    graph: TransmissionGraph | None = None
    #: factor id -> version of the plugin that declares it; part of the scenario identity.
    factor_versions: dict[str, str] = field(default_factory=dict)
    _sampled: ScenarioDraws | None = field(default=None, init=False, repr=False)
    _own: dict[str, np.ndarray] = field(default_factory=dict, init=False, repr=False)

    @property
    def parameters(self) -> dict[str, MacroParameter]:
        return self.scenario_set.parameters

    @property
    def replicates(self) -> int:
        return self.scenario_set.replicates

    @property
    def points(self) -> int:
        return self.scenario_set.points

    @property
    def sampled(self) -> ScenarioDraws:
        if self._sampled is None:
            self._sampled = self.scenario_set.sample(self.seed)
        return self._sampled

    @property
    def macro_draws_sha256(self) -> str:
        return self.sampled.sha256

    def draws(self, name: str) -> np.ndarray:
        return self.sampled.stacked(name)

    def central(self, name: str) -> float:
        return self.scenario_set.marginals()[name].central_value()

    def parameters_for(self, factor_id: str, key: str | None = None) -> list[str]:
        return sorted(
            name
            for name, parameter in self.parameters.items()
            if parameter.factor == factor_id and (key is None or parameter.key == key)
        )

    def idiosyncratic(self, name: str) -> np.ndarray:
        if name not in self._own:
            shock = next(
                (item for item in self.scenario_set.idiosyncratic if item.name == name), None
            )
            if shock is None:
                raise KeyError(f"no idiosyncratic shock {name!r} in the scenario set")
            self._own[name] = idiosyncratic_draws(shock, self.seed, self.points, self.replicates)
        return self._own[name]

    @property
    def scenario_id(self) -> str:
        return scenario_id(
            self.scenario_set,
            self.seed,
            self.as_of,
            self.horizon,
            self.graph,
            self.factor_versions,
            self.macro_draws_sha256,
        )


def scenario_id(scenario_set, seed, as_of, horizon, graph, factor_versions, macro_hash) -> str:
    payload = {
        "spec": scenario_set.spec(),
        "seed": seed,
        "as_of": as_of.isoformat(),
        "horizon": horizon,
        "graph": None if graph is None else graph.model_dump(mode="json"),
        "factor_versions": dict(sorted(factor_versions.items())),
        "macro_draws_sha256": macro_hash,
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(text.encode("utf-8")).hexdigest()
