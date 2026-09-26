"""Shapley decomposition of the channel contributions (spec 14).

One game, one metric: ``v(S)`` is a full recomputation with only the channels in ``S``
active. The empty coalition is the actual base calculation, so the explained effect is
``v(M) - v(empty)`` and the contributions must add up to it.

A Shapley value explains how the model's own output splits between channels. It is not
evidence of a causal relation.
"""

from dataclasses import dataclass
from itertools import combinations
from math import factorial

import numpy as np

EXACT_LIMIT = 8
DEFAULT_TOLERANCE = 1e-9
BATCH = 64
MAX_PERMUTATIONS = 20000

NOT_EFFICIENT_FLAG = "shapley_not_efficient"
NOT_CONVERGED_FLAG = "shapley_not_converged"


@dataclass(frozen=True)
class ShapleyResult:
    contributions: dict[str, float]
    explained: float
    residual: float
    permutations: int
    exact: bool
    halfwidths: dict[str, float]
    flags: tuple[str, ...]


def exact(players: list[str], value) -> dict[str, float]:
    """``phi_i = sum_S |S|!(m-|S|-1)!/m! [v(S+i) - v(S)]`` (spec 14)."""
    m = len(players)
    cache: dict[frozenset[str], float] = {}

    def evaluate(coalition: frozenset[str]) -> float:
        if coalition not in cache:
            cache[coalition] = float(value(set(coalition)))
        return cache[coalition]

    contributions = {}
    for player in players:
        others = [name for name in players if name != player]
        total = 0.0
        for size in range(m):
            weight = factorial(size) * factorial(m - size - 1) / factorial(m)
            for subset in combinations(others, size):
                coalition = frozenset(subset)
                total += weight * (evaluate(coalition | {player}) - evaluate(coalition))
        contributions[player] = total
    return contributions


def permutation(
    players: list[str],
    value,
    seed: int,
    *,
    abs_tol: float = 1e-3,
    rel_tol: float = 0.01,
    scale: float = 0.0,
    max_permutations: int = MAX_PERMUTATIONS,
):
    """Sampled Shapley with common random numbers across coalitions (spec 14).

    Every coalition is evaluated on the same underlying scenario points, so the differences
    that drive the estimate are not polluted by sampling noise between coalitions.
    """
    rng = np.random.default_rng(seed)
    cache: dict[frozenset[str], float] = {}

    def evaluate(coalition: frozenset[str]) -> float:
        if coalition not in cache:
            cache[coalition] = float(value(set(coalition)))
        return cache[coalition]

    empty = evaluate(frozenset())
    full = evaluate(frozenset(players))
    explained = full - empty
    samples: dict[str, list[float]] = {player: [] for player in players}
    drawn = 0
    while drawn < max_permutations:
        for _ in range(BATCH):
            order = list(rng.permutation(players))
            coalition: frozenset[str] = frozenset()
            previous = empty
            for player in order:
                coalition = coalition | {player}
                current = evaluate(coalition)
                samples[player].append(current - previous)
                previous = current
            drawn += 1
        halfwidths = {player: _halfwidth(values) for player, values in samples.items()}
        limit = max(abs_tol, rel_tol * max(abs(explained), scale))
        if all(width <= limit for width in halfwidths.values()):
            break
    contributions = {player: float(np.mean(values)) for player, values in samples.items()}
    return contributions, explained, drawn, halfwidths


def contributions(
    players: list[str],
    value,
    seed: int = 0,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    abs_tol: float = 1e-3,
    rel_tol: float = 0.01,
    scale: float = 0.0,
) -> ShapleyResult:
    """Channel contributions with the efficiency identity checked (spec 14)."""
    flags: list[str] = []
    players = sorted(players)
    if not players:
        return ShapleyResult({}, 0.0, 0.0, 0, True, {}, ())
    use_exact = len(players) <= EXACT_LIMIT
    if use_exact:
        result = exact(players, value)
        explained = float(value(set(players))) - float(value(set()))
        halfwidths = dict.fromkeys(players, 0.0)
        permutations = 0
    else:
        result, explained, permutations, halfwidths = permutation(
            players, value, seed, abs_tol=abs_tol, rel_tol=rel_tol, scale=scale
        )
        limit = max(abs_tol, rel_tol * max(abs(explained), scale))
        if any(width > limit for width in halfwidths.values()):
            flags.append(NOT_CONVERGED_FLAG)

    residual = float(sum(result.values()) - explained)
    efficiency_limit = max(tolerance, abs_tol) if not use_exact else tolerance
    if abs(residual) > efficiency_limit:
        flags.append(NOT_EFFICIENT_FLAG)
    return ShapleyResult(
        contributions=result,
        explained=explained,
        residual=residual,
        permutations=permutations,
        exact=use_exact,
        halfwidths=halfwidths,
        flags=tuple(flags),
    )


def _halfwidth(values: list[float], confidence: float = 1.96) -> float:
    array = np.asarray(values, dtype=float)
    if array.size < 2:
        return float("inf")
    return float(confidence * array.std(ddof=1) / np.sqrt(array.size))
