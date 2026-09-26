"""Scenario generation and numerical error (spec 13).

Error is estimated across ``R >= 8`` independently scrambled Sobol replicates, not by
bootstrapping points of a single grid: the points of one Sobol net are not independent, so
a bootstrap of them understates the error.

The central scenario is stored separately from the mean of the distribution. It is a
management scenario, not a statistical moment.
"""

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

import numpy as np
from scipy import stats
from scipy.stats import qmc

MIN_REPLICATES = 8
_EPS = 2.0**-53

NOT_POSITIVE_DEFINITE = (
    "the correlation matrix must be symmetric and positive definite; silent repair is not permitted"
)


@dataclass(frozen=True)
class Marginal:
    """A marginal distribution with domain-respecting bounds (spec 13.1)."""

    #: ``lognormal`` reads ``mean`` and ``sigma`` as the mean and deviation of the log.
    kind: Literal["point", "triangular", "uniform", "truncated_normal", "lognormal", "empirical"]
    value: float | None = None
    low: float | None = None
    mode: float | None = None
    high: float | None = None
    mean: float | None = None
    sigma: float | None = None
    samples: tuple[float, ...] | None = None
    #: Management central value, kept apart from the distribution mean.
    central: float | None = None

    def __post_init__(self):
        if self.kind == "point" and self.value is None:
            raise ValueError("point requires value")
        if self.kind == "triangular":
            if None in (self.low, self.mode, self.high):
                raise ValueError("triangular requires low, mode and high")
            if not self.low <= self.mode <= self.high or self.low >= self.high:
                raise ValueError("require low <= mode <= high and low < high")
        if self.kind == "uniform":
            if None in (self.low, self.high) or self.low >= self.high:
                raise ValueError("uniform requires low < high")
        if self.kind == "truncated_normal":
            if None in (self.mean, self.sigma, self.low, self.high):
                raise ValueError("truncated_normal requires mean, sigma, low and high")
            if self.sigma <= 0 or self.low >= self.high:
                raise ValueError("require sigma > 0 and low < high")
        if self.kind == "lognormal":
            if None in (self.mean, self.sigma) or self.sigma <= 0:
                raise ValueError("lognormal requires mean and sigma > 0")
        if self.kind == "empirical" and not self.samples:
            raise ValueError("empirical requires samples")

    def ppf(self, u) -> np.ndarray:
        u = np.asarray(u, dtype=float)
        if self.kind == "point":
            return np.full(u.shape, float(self.value))
        if self.kind == "triangular":
            width = self.high - self.low
            return stats.triang.ppf(u, c=(self.mode - self.low) / width, loc=self.low, scale=width)
        if self.kind == "uniform":
            return self.low + (self.high - self.low) * u
        if self.kind == "truncated_normal":
            return stats.truncnorm.ppf(
                u,
                (self.low - self.mean) / self.sigma,
                (self.high - self.mean) / self.sigma,
                loc=self.mean,
                scale=self.sigma,
            )
        if self.kind == "lognormal":
            return np.exp(self.mean + self.sigma * stats.norm.ppf(np.clip(u, _EPS, 1 - _EPS)))
        samples = np.sort(np.asarray(self.samples, dtype=float))
        return samples[np.clip((u * samples.size).astype(int), 0, samples.size - 1)]

    def central_value(self) -> float:
        """The management central scenario, never the distribution mean by default."""
        if self.central is not None:
            return float(self.central)
        if self.kind == "point":
            return float(self.value)
        if self.kind == "triangular":
            return float(self.mode)
        if self.kind == "uniform":
            return float((self.low + self.high) / 2.0)
        if self.kind == "truncated_normal":
            return float(self.mean)
        if self.kind == "lognormal":
            return float(np.exp(self.mean + self.sigma**2 / 2.0))
        return float(np.median(np.asarray(self.samples, dtype=float)))


def sobol_replicates(dimensions: int, seed: int, points: int, replicates: int = MIN_REPLICATES):
    """``R`` independently scrambled Sobol nets of ``2^m`` points each (spec 13.3).

    Replicate ``r`` is scrambled by its own generator seeded with ``(seed, r)``, so the
    replicates of neighbouring seeds share nothing.
    """
    if replicates < MIN_REPLICATES:
        raise ValueError(f"at least {MIN_REPLICATES} independent replicates are required")
    if points <= 0 or points & (points - 1):
        raise ValueError("points must be a power of two")
    m = points.bit_length() - 1
    return [
        qmc.Sobol(
            d=dimensions, scramble=True, rng=np.random.default_rng([seed, replicate])
        ).random_base2(m)
        for replicate in range(replicates)
    ]


def gaussian_copula(u, correlation) -> np.ndarray:
    """``u' = Phi(Phi^-1(u) L^T)`` with ``L L^T = Corr`` (spec 13.2)."""
    matrix = np.asarray(correlation, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError("the correlation matrix must be square")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(NOT_POSITIVE_DEFINITE)
    if not np.allclose(matrix, matrix.T, atol=1e-12, rtol=0.0):
        raise ValueError(NOT_POSITIVE_DEFINITE)
    if not np.allclose(np.diag(matrix), 1.0, atol=1e-12, rtol=0.0):
        raise ValueError(NOT_POSITIVE_DEFINITE)
    unit = np.asarray(u, dtype=float)
    if unit.ndim == 0 or unit.shape[-1] != matrix.shape[0]:
        raise ValueError("copula points and correlation matrix dimensions must agree")
    if not np.all(np.isfinite(unit)) or np.any((unit < 0.0) | (unit > 1.0)):
        raise ValueError("copula points must be finite values in [0, 1]")
    try:
        lower = np.linalg.cholesky(matrix)
    except np.linalg.LinAlgError as exc:
        raise ValueError(NOT_POSITIVE_DEFINITE) from exc
    z = stats.norm.ppf(np.clip(unit, _EPS, 1 - _EPS))
    return stats.norm.cdf(z @ lower.T)


@dataclass
class ScenarioDraws:
    """One replicate set of joint scenario realisations."""

    names: tuple[str, ...]
    #: ``replicates`` arrays shaped ``(points, len(names))``.
    replicates: list[np.ndarray]
    seed: int

    @property
    def points(self) -> int:
        return self.replicates[0].shape[0]

    def column(self, name: str, replicate: int = 0) -> np.ndarray:
        return self.replicates[replicate][:, self.names.index(name)]

    def stacked(self, name: str) -> np.ndarray:
        """All replicates of one parameter, shaped ``(replicates, points)``."""
        return np.stack([self.column(name, r) for r in range(len(self.replicates))])

    @property
    def sha256(self) -> str:
        payload = b"".join(
            np.ascontiguousarray(block, dtype="<f8").tobytes() for block in self.replicates
        )
        return sha256(payload).hexdigest()


def draw(
    marginals: dict[str, Marginal],
    seed: int,
    points: int,
    *,
    replicates: int = MIN_REPLICATES,
    correlation=None,
) -> ScenarioDraws:
    if not marginals:
        raise ValueError("at least one marginal is required")
    names = tuple(sorted(marginals))
    blocks = []
    for unit in sobol_replicates(len(names), seed, points, replicates):
        if correlation is not None:
            unit = gaussian_copula(unit, correlation)
        values = np.empty_like(unit)
        for column, name in enumerate(names):
            values[:, column] = marginals[name].ppf(unit[:, column])
        blocks.append(values)
    return ScenarioDraws(names=names, replicates=blocks, seed=seed)


@dataclass(frozen=True)
class ReplicateEstimate:
    """Point estimate and its error interval built from independent replicates."""

    mean: float
    standard_error: float
    halfwidth: float
    replicates: int

    def interval(self) -> tuple[float, float]:
        return self.mean - self.halfwidth, self.mean + self.halfwidth


def estimate(per_replicate, confidence: float = 0.95) -> ReplicateEstimate:
    """``SE = sqrt(sum (theta_r - mean)^2 / (R(R-1)))`` (spec 13.3)."""
    values = np.asarray(per_replicate, dtype=float).reshape(-1)
    r = values.size
    if r < MIN_REPLICATES:
        raise ValueError(
            f"an error interval needs at least {MIN_REPLICATES} independent replicates"
        )
    mean = float(values.mean())
    standard_error = float(np.sqrt(np.sum((values - mean) ** 2) / (r * (r - 1))))
    critical = float(stats.t.ppf(0.5 + confidence / 2.0, df=r - 1))
    return ReplicateEstimate(
        mean=mean,
        standard_error=standard_error,
        halfwidth=critical * standard_error,
        replicates=r,
    )


@dataclass(frozen=True)
class Tolerance:
    """Business-set precision target for one reported quantity (spec 13.3)."""

    abs_tol: float
    rel_tol: float
    scale: float = 0.0

    def satisfied_by(self, value: ReplicateEstimate) -> bool:
        limit = max(self.abs_tol, self.rel_tol * max(abs(value.mean), self.scale))
        return value.halfwidth <= limit


#: Defaults by business purpose; a deployment overrides them per reported quantity.
DEFAULT_TOLERANCES: dict[str, Tolerance] = {
    "expected_loss": Tolerance(abs_tol=0.01, rel_tol=0.02, scale=1.0),
    "breach_probability": Tolerance(abs_tol=0.01, rel_tol=0.05, scale=0.05),
    "p95": Tolerance(abs_tol=0.05, rel_tol=0.02, scale=1.0),
    "es95": Tolerance(abs_tol=0.05, rel_tol=0.02, scale=1.0),
}
