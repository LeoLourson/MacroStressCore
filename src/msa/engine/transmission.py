"""Temporal shock transmission graph (spec 3).

Every node carries a monthly signal ``y[v, t]`` built from its own direct external shock
plus the signals arriving along incoming edges, each spread over time by a delay kernel.
Signals are arrays shaped ``(..., H)``; leading axes broadcast over Monte Carlo draws.

This replaces the earlier scalar simple-path fold: lags now compose by convolution of the
edge kernels instead of collapsing into a single weight, so a two-month edge followed by a
three-month edge lands in month five rather than being averaged away.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from .quantities import UnitMismatch, check_kind

Coordinate = Literal["log_factor", "additive"]

MISSING_HISTORY_FLAG = "missing_pre_horizon_history"
OUT_OF_DOMAIN_FLAG = "out_of_domain"

_KERNEL_TOLERANCE = 1e-12


class GraphCycle(ValueError):
    """Raised when the transmission graph is not acyclic (spec 3.4)."""


@dataclass(frozen=True)
class DelayKernel:
    """Discrete delay kernel ``K_e(l)``, ``l = 0..L_e``, non-negative and summing to one."""

    weights: tuple[float, ...]

    def __post_init__(self):
        if not self.weights:
            raise ValueError("a delay kernel needs at least one weight")
        if any(weight < 0 for weight in self.weights):
            raise ValueError("delay kernel weights must be non-negative")
        total = sum(self.weights)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"delay kernel weights must sum to 1, got {total}")

    @property
    def max_lag(self) -> int:
        return len(self.weights) - 1

    @classmethod
    def fixed(cls, lag: int) -> "DelayKernel":
        """All of the effect lands in month ``t + lag``."""
        if lag < 0:
            raise ValueError("lag must be non-negative")
        return cls(tuple([0.0] * lag + [1.0]))

    @classmethod
    def uniform(cls, max_lag: int) -> "DelayKernel":
        """The effect spreads evenly over months ``t .. t + max_lag``."""
        if max_lag < 0:
            raise ValueError("max_lag must be non-negative")
        n = max_lag + 1
        return cls(tuple([1.0 / n] * n))

    def convolve(self, other: "DelayKernel") -> "DelayKernel":
        """Kernel of two edges in series: lags add along the path (spec 3.4)."""
        combined = np.convolve(np.asarray(self.weights), np.asarray(other.weights))
        return DelayKernel(tuple(combined))


@dataclass(frozen=True)
class TemporalNode:
    id: str
    coordinate: Coordinate
    #: Quantity kind of the underlying driver; ``additive`` nodes need it to add up.
    kind: str = "relative_change"

    def __post_init__(self):
        if self.coordinate not in ("log_factor", "additive"):
            raise ValueError(f"unknown node coordinate: {self.coordinate!r}")
        check_kind(self.kind)
        if self.coordinate == "log_factor" and self.kind not in (
            "relative_change",
            "log_change",
        ):
            raise UnitMismatch("a log_factor node must carry a proportional quantity")


@dataclass(frozen=True)
class Conversion:
    """Declared coordinate change carried by an edge (spec 3.1).

    An edge may only cross coordinates when the change is written down and checkable:
    ``scale`` is how many units of the destination coordinate one unit of the source
    signal becomes.
    """

    to_kind: str
    scale: float

    def __post_init__(self):
        check_kind(self.to_kind)
        if not np.isfinite(self.scale):
            raise ValueError("a conversion scale must be finite")


@dataclass(frozen=True)
class TemporalEdge:
    src: str
    dst: str
    sign: int
    sensitivity: float
    kernel: DelayKernel
    #: Required when the edge joins nodes of different coordinates.
    conversion: Conversion | None = None

    def __post_init__(self):
        if self.sign not in (-1, 1):
            raise ValueError("edge sign must be -1 or +1")
        if self.sensitivity < 0:
            raise ValueError("edge sensitivity must be non-negative")

    def gain(self) -> float:
        scale = 1.0 if self.conversion is None else self.conversion.scale
        return self.sign * self.sensitivity * scale


@dataclass(frozen=True)
class Domain:
    """Admissible range of a driver (spec 3.5). Values outside are flagged, never clipped."""

    lower: float | None = None
    upper: float | None = None
    #: True when ``lower`` itself is admissible (DSO >= 0) and False when it is not (price > 0).
    lower_closed: bool = True

    def contains(self, value) -> np.ndarray:
        value = np.asarray(value, dtype=float)
        ok = np.isfinite(value)
        if self.lower is not None:
            ok &= value >= self.lower if self.lower_closed else value > self.lower
        if self.upper is not None:
            ok &= value <= self.upper
        return ok


#: Driver domains named by the spec in 3.5.
POSITIVE_MULTIPLIER = Domain(lower=0.0, lower_closed=False)
NON_NEGATIVE_DAYS = Domain(lower=0.0)


@dataclass
class TemporalGraph:
    nodes: list[TemporalNode]
    edges: list[TemporalEdge] = field(default_factory=list)

    def __post_init__(self):
        ids = [node.id for node in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate node ids in the transmission graph")
        known = set(ids)
        for edge in self.edges:
            if edge.src not in known or edge.dst not in known:
                raise ValueError(f"edge {edge.src}->{edge.dst} references an unknown node")
            self._check_edge_units(edge)

    def _check_edge_units(self, edge: TemporalEdge) -> None:
        src, dst = self.node(edge.src), self.node(edge.dst)
        if src.coordinate == dst.coordinate:
            if edge.conversion is not None and edge.conversion.to_kind != dst.kind:
                raise UnitMismatch(
                    f"edge {edge.src}->{edge.dst} converts to {edge.conversion.to_kind} "
                    f"but node {dst.id} carries {dst.kind}"
                )
            return
        if edge.conversion is None:
            raise UnitMismatch(
                f"edge {edge.src}->{edge.dst} crosses coordinates "
                f"({src.coordinate} -> {dst.coordinate}) without an explicit conversion"
            )
        if edge.conversion.to_kind != dst.kind:
            raise UnitMismatch(
                f"edge {edge.src}->{edge.dst} converts to {edge.conversion.to_kind} "
                f"but node {dst.id} carries {dst.kind}"
            )

    def node(self, node_id: str) -> TemporalNode:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(node_id)

    def incoming(self) -> dict[str, list[TemporalEdge]]:
        table: dict[str, list[TemporalEdge]] = defaultdict(list)
        for edge in self.edges:
            table[edge.dst].append(edge)
        return table

    def topological_order(self) -> list[str]:
        """Kahn's algorithm; zero-lag edges need sources evaluated first (spec 3.1)."""
        indegree = {node.id: 0 for node in self.nodes}
        successors: dict[str, list[str]] = defaultdict(list)
        for edge in self.edges:
            indegree[edge.dst] += 1
            successors[edge.src].append(edge.dst)
        ready = sorted(node for node, degree in indegree.items() if degree == 0)
        order: list[str] = []
        while ready:
            current = ready.pop(0)
            order.append(current)
            for successor in sorted(successors[current]):
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    ready.append(successor)
            ready.sort()
        if len(order) != len(self.nodes):
            raise GraphCycle("the transmission graph must be acyclic")
        return order

    def propagate(
        self,
        direct: dict[str, np.ndarray],
        *,
        horizon: int,
        history: dict[str, np.ndarray] | None = None,
        flags: list[str] | None = None,
    ) -> dict[str, np.ndarray]:
        """Full signals ``y[v, t]`` for every node (spec 3.4).

        ``direct`` holds already-converted direct inputs ``d[v, t]`` shaped ``(..., H)``.
        ``history`` holds pre-horizon signals with ``history[v][k] = y[v, -k]``.
        """
        if horizon < 1:
            raise ValueError("horizon must be at least one month")
        unknown = set(direct) - {node.id for node in self.nodes}
        if unknown:
            raise KeyError(f"direct input for unknown nodes: {sorted(unknown)}")

        order = self.topological_order()
        incoming = self.incoming()
        shape = _broadcast_shape(direct.values(), horizon)
        signals = {node.id: np.zeros(shape, dtype=float) for node in self.nodes}
        inputs = {
            node.id: np.broadcast_to(np.asarray(direct.get(node.id, 0.0), dtype=float), shape)
            for node in self.nodes
        }
        history = history or {}
        needs_history = _edges_reaching_before_horizon(self.edges)
        if flags is not None and needs_history and not history:
            flags.append(MISSING_HISTORY_FLAG)

        for index in range(horizon):
            for node_id in order:
                total = inputs[node_id][..., index]
                for edge in incoming[node_id]:
                    arrived = np.zeros(shape[:-1], dtype=float)
                    for lag, weight in enumerate(edge.kernel.weights):
                        if weight == 0.0:
                            continue
                        source = index - lag
                        if source >= 0:
                            past = signals[edge.src][..., source]
                        else:
                            past = _history_value(history, edge.src, source, shape[:-1])
                        arrived = arrived + weight * past
                    total = total + edge.gain() * arrived
                signals[node_id][..., index] = total
        return signals


def direct_input(node: TemporalNode, shock) -> np.ndarray:
    """Convert an external shock in its natural scale into the node coordinate (spec 3.2).

    ``log_factor`` takes a relative change ``xi > -1`` and yields ``ln(1 + xi)``;
    ``additive`` takes the shock already expressed in the node's own unit.
    """
    value = np.asarray(shock, dtype=float)
    if node.coordinate == "additive":
        return value
    if np.any(value <= -1.0):
        raise ValueError(f"relative shock for {node.id} must be greater than -1")
    return np.log1p(value)


def relative_change(signal) -> np.ndarray:
    """``x = exp(y) - 1`` for a log_factor node (spec 3.5)."""
    return np.expm1(np.asarray(signal, dtype=float))


def check_domain(name: str, value, domain: Domain, flags: list[str] | None = None) -> bool:
    """Report whether ``value`` stays admissible. Out-of-domain values are never clipped."""
    ok = bool(np.all(domain.contains(value)))
    if not ok and flags is not None:
        flag = f"{OUT_OF_DOMAIN_FLAG}:{name}"
        if flag not in flags:
            flags.append(flag)
    return ok


def _edges_reaching_before_horizon(edges: list[TemporalEdge]) -> bool:
    return any(edge.kernel.max_lag > 0 for edge in edges)


def _broadcast_shape(arrays, horizon: int) -> tuple[int, ...]:
    shapes = []
    for array in arrays:
        value = np.asarray(array, dtype=float)
        if value.ndim == 0:
            continue
        if value.shape[-1] != horizon:
            raise ValueError(f"direct input must end in the horizon axis of length {horizon}")
        shapes.append(value.shape[:-1])
    lead = np.broadcast_shapes(*shapes) if shapes else ()
    return (*lead, horizon)


def _history_value(
    history: dict[str, np.ndarray], node_id: str, source: int, shape: tuple[int, ...]
) -> np.ndarray:
    """``source`` is a 0-based index below zero; month number is ``source + 1``."""
    past = history.get(node_id)
    if past is None:
        return np.zeros(shape, dtype=float)
    offset = -source - 1
    past = np.asarray(past, dtype=float)
    if offset >= past.shape[-1]:
        return np.zeros(shape, dtype=float)
    return np.broadcast_to(past[..., offset], shape)
