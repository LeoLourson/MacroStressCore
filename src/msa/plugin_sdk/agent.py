"""Agent plugins and workflows: the nodes and processes of the run's execution graph.

The execution graph (LangGraph) says which agents and calculation steps run and in what
order; it is a different thing from the economic graph of an event. A workflow is declared
as data: its core nodes, their edges and routes, and named extension points. An agent
plugin joins a workflow at an extension point; agents of one point are ordered by their
``before``/``after`` relations and those without a relation run in parallel.

An agent reads only what it ``consumes`` and writes only to its own namespace of the run
state (``extensions[<agent_id>]``); it cannot change the scenario, the results or the
report, and cannot pass a human stop. A subgraph keeps its own state behind explicit
input and output adapters. Cycles are allowed inside a subgraph, bounded by
``max_iterations``.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

#: Prefix of keys a plugin agent reads from another agent's namespace: ``ext:<agent>/<key>``.
EXTENSION_PREFIX = "ext:"


class AgentTools(Protocol):
    """The MCP tools an agent declared in ``AgentPlugin.tools``, through the run's gateway.

    A tool is named ``<server>.<tool>``. Calling a tool the agent did not declare is refused
    (``PermissionError``). Every call is audited under the agent's node of the run.
    """

    def call(self, tool: str, /, **arguments) -> Any:
        """A call the agent's code makes itself (initiator ``workflow``)."""
        ...

    def call_as(
        self, tool: str, arguments: dict, *, initiator: str = "llm", call_id: str | None = None
    ) -> Any:
        """A call an LLM chose; ``tool`` may also be the function name of ``functions()``."""
        ...

    def functions(self) -> list[dict]:
        """The declared tools as OpenAI function definitions, for ``complete_with_tools``."""
        ...


@dataclass(frozen=True)
class AgentContext:
    """What an agent is built with: its declaration, the run's services, the registry, the
    run's LLM client and its declared tools.

    ``llm`` is ``None`` when the deployment runs without a model (``mock``): an agent that
    needs one says so in its output or fails with that reason. ``tools`` is an
    ``AgentTools`` limited to ``AgentPlugin.tools``; outside a run with MCP servers (a unit
    test of the graph) a call fails with its reason, and a plugin agent's failure is
    recorded in its own namespace.
    """

    agent: "AgentPlugin"
    services: Any = None
    registry: Any = None
    llm: Any = None
    tools: AgentTools | None = None


@dataclass(frozen=True)
class AgentPlugin:
    agent_id: str
    version: str
    label: str
    #: ``fn(context) -> node``; a node is ``fn(view: dict) -> dict`` or a compiled subgraph.
    build: Callable[[AgentContext], Any]
    #: workflow id -> extension point the agent joins.
    extends: dict[str, str] = field(default_factory=dict)
    #: State keys the agent reads: core keys of the workflow or ``ext:<agent>/<key>``.
    consumes: tuple[str, ...] = ()
    #: Keys the agent writes, inside its own namespace.
    produces: tuple[str, ...] = ()
    #: MCP tools the agent may call, ``server.tool``; the compiler checks each exists and
    #: ``AgentContext.tools`` refuses any other.
    tools: tuple[str, ...] = ()
    input_schema: type[BaseModel] | None = None
    output_schema: type[BaseModel] | None = None
    timeout_s: float = 120.0
    #: Attempts on an expected failure (1-3).
    retries: int = 1
    max_iterations: int = 1
    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()
    #: Adapters of a subgraph: the run state view -> its input; its output -> the agent's.
    subgraph_input: Callable[[dict], dict] | None = None
    subgraph_output: Callable[[dict], dict] | None = None
    #: A core agent owns core state keys; only the workflow's own agents are core.
    core: bool = False
    enabled_by_default: bool = True
    description: str = ""


@dataclass(frozen=True)
class NodeSpec:
    node_id: str
    #: The agent that runs here; ``None`` for a pass-through (an extension point).
    agent: str | None
    stage: str
    #: The node stops for a person (``interrupt``).
    human: bool = False
    #: The node runs once per branch (``Send``), e.g. once per position.
    branch: str | None = None


@dataclass(frozen=True)
class Route:
    """A conditional edge: ``router(state)`` names the next node(s), ``END`` or ``Send``s."""

    source: str
    router: Callable[[dict], Any]
    targets: tuple[str, ...]


@dataclass(frozen=True)
class ExtensionPoint:
    """A place plugin agents join: a pass-through node of the workflow and the core keys
    the workflow guarantees there."""

    point_id: str
    label: str
    available: tuple[str, ...] = ()


@dataclass(frozen=True)
class StageSpec:
    """A step of the run as the screens show it, with the nodes it groups."""

    stage_id: str
    title: str
    nodes: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowSpec:
    workflow_id: str
    version: str
    label: str
    state_schema: type
    input_schema: type
    nodes: tuple[NodeSpec, ...]
    #: Static edges ``(source, target)``; ``"__start__"`` and ``"__end__"`` are allowed.
    edges: tuple[tuple[str, str], ...]
    routes: tuple[Route, ...] = ()
    extension_points: tuple[ExtensionPoint, ...] = ()
    stages: tuple[StageSpec, ...] = ()
    #: State keys only core agents may write.
    core_keys: frozenset[str] = frozenset()
    description: str = ""

    def node(self, node_id: str) -> NodeSpec:
        return next(node for node in self.nodes if node.node_id == node_id)
