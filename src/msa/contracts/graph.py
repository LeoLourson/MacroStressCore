"""The economic graph of an event: event -> channel -> sector -> factor (spec 3).

It says how the event acts on the economy; the run's execution graph (LangGraph) is a
separate thing. Factor nodes name registered factors (``msa.plugin_sdk.FactorSpec``).
Graph-scope factors propagate through sectors; direct factors identify an explicit key.
Edges into direct factors describe causality only and do not scale their scenario shocks.
"""

from collections import deque
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .common import Contract, Identifier, NonNegative, Number, Positive
from .evidence import Evidence


class PointDistribution(Contract):
    family: Literal["point"] = "point"
    value: NonNegative


class TriangularDistribution(Contract):
    family: Literal["triangular"] = "triangular"
    low: NonNegative
    mode: NonNegative
    high: Positive

    @model_validator(mode="after")
    def ordered(self):
        if not self.low <= self.mode <= self.high or self.low == self.high:
            raise ValueError("Require low <= mode <= high and low < high")
        return self


class UniformDistribution(Contract):
    family: Literal["uniform"] = "uniform"
    low: NonNegative
    high: Positive

    @model_validator(mode="after")
    def ordered(self):
        if self.low >= self.high:
            raise ValueError("Require low < high")
        return self


class LogNormalDistribution(Contract):
    family: Literal["lognormal"] = "lognormal"
    mu: Number
    sigma: Positive


Distribution = Annotated[
    PointDistribution | TriangularDistribution | UniformDistribution | LogNormalDistribution,
    Field(discriminator="family"),
]


class Node(Contract):
    """A node of the economic graph; ``key`` identifies a direct factor instance."""

    id: Identifier
    kind: Literal["event", "channel", "sector", "factor"]
    label: Identifier
    okved: Identifier | None = None
    factor: Identifier | None = None
    key: Identifier | None = None

    @model_validator(mode="after")
    def kind_fields(self):
        if (self.kind == "factor") != (self.factor is not None):
            raise ValueError("Only factor nodes must specify factor")
        if (self.kind == "sector") != (self.okved is not None):
            raise ValueError("Only sector nodes must specify okved")
        if self.key is not None and self.kind != "factor":
            raise ValueError("Only factor nodes may specify key")
        return self


class Edge(Contract):
    src: Identifier
    dst: Identifier
    sign: Literal[-1, 1]
    elasticity: Distribution
    lag_months: int = Field(strict=True, ge=0, le=36)
    evidence: list[Evidence] = Field(min_length=1)

    @field_validator("sign", mode="before")
    @classmethod
    def integer_sign(cls, value):
        if type(value) is not int:
            raise ValueError("sign must be the integer -1 or 1")
        return value


class TransmissionGraph(Contract):
    event_id: Identifier
    nodes: list[Node] = Field(min_length=1)
    edges: list[Edge]
    # Keys are factor NODE IDs: two industries may have different revenue elasticities.
    factor_elasticity: dict[Identifier, Number] = {}

    @model_validator(mode="after")
    def valid_dag(self):
        nodes = {node.id: node for node in self.nodes}
        if len(nodes) != len(self.nodes):
            raise ValueError("Node IDs must be unique")
        if self.event_id not in nodes or nodes[self.event_id].kind != "event":
            raise ValueError("event_id must identify an event node")
        if any(key not in nodes or nodes[key].kind != "factor" for key in self.factor_elasticity):
            raise ValueError("factor_elasticity keys must identify factor nodes")
        indegree = dict.fromkeys(nodes, 0)
        children = {node: [] for node in nodes}
        pairs = set()
        for edge in self.edges:
            if edge.src not in nodes or edge.dst not in nodes:
                raise ValueError("Edges must reference existing nodes")
            if (edge.src, edge.dst) in pairs:
                raise ValueError("Duplicate edge")
            pairs.add((edge.src, edge.dst))
            indegree[edge.dst] += 1
            children[edge.src].append(edge.dst)
        queue = deque(node for node, degree in indegree.items() if degree == 0)
        visited = 0
        while queue:
            visited += 1
            for child in children[queue.popleft()]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        if visited != len(nodes):
            raise ValueError("Transmission graph must be acyclic")
        return self

    def simple_paths(self, src: str, dst: str) -> list[list[Edge]]:
        ids = {node.id for node in self.nodes}
        if src not in ids or dst not in ids:
            raise KeyError(src if src not in ids else dst)
        paths = []
        stack = [(src, [], {src})]
        while stack:
            node, path, seen = stack.pop()
            if node == dst:
                paths.append(path)
            else:
                for edge in reversed(self.edges):
                    if edge.src == node and edge.dst not in seen:
                        stack.append((edge.dst, [*path, edge], seen | {edge.dst}))
        return paths
