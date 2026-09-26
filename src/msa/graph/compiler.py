"""Compiling a declared workflow and its agent plugins into a LangGraph graph.

The compiler places the agents of each extension point after its pass-through node,
layered by their ``before``/``after`` relations: agents of one layer run in parallel and
the next layer waits for all of them. Before anything runs it checks the declarations:
unknown agents and points, missing and cyclic dependencies, reads of keys nobody
provides, writes into core state or into another agent's namespace, MCP tools no server
defines, and SDK and version ranges (through the registry). Every agent is built with the
run's LLM client and a gateway limited to the tools it declared.
"""

import concurrent.futures
import contextvars
from collections.abc import Iterable

from langgraph.graph import END, START, StateGraph

from msa.agents.base import AgentFailure
from msa.mcp.tools import DeclaredTools
from msa.plugin_sdk.agent import EXTENSION_PREFIX, AgentContext, AgentPlugin, WorkflowSpec

from .runtime import journaled

IDENTITY_KEYS = ("run_id", "mode", "graph_revision", "as_of", "portfolio_id")


class WorkflowError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Workflow cannot be compiled:\n- " + "\n- ".join(problems))


def extension_agents(spec: WorkflowSpec, registry, enabled: Iterable[str] = ()) -> dict:
    """Extension point -> the plugin agents that join it in this workflow."""
    enabled = set(enabled)
    points = {point.point_id: [] for point in spec.extension_points}
    for agent in registry.agents.values():
        if agent.core:
            continue
        point = agent.extends.get(spec.workflow_id)
        if point is None:
            continue
        if not (agent.enabled_by_default or agent.agent_id in enabled):
            continue
        points.setdefault(point, []).append(agent)
    return points


def layers(agents: list[AgentPlugin]) -> list[list[AgentPlugin]]:
    """Topological layers by ``before``/``after``; raises on an unknown or cyclic relation."""
    ids = {agent.agent_id for agent in agents}
    after: dict[str, set[str]] = {agent.agent_id: set() for agent in agents}
    for agent in agents:
        for other in agent.after:
            if other not in ids:
                raise WorkflowError([f"{agent.agent_id} runs after unknown agent {other!r}"])
            after[agent.agent_id].add(other)
        for other in agent.before:
            if other not in ids:
                raise WorkflowError([f"{agent.agent_id} runs before unknown agent {other!r}"])
            after[other].add(agent.agent_id)
    result, placed = [], set()
    while len(placed) < len(ids):
        layer = sorted(a for a in ids - placed if after[a] <= placed)
        if not layer:
            raise WorkflowError([f"cyclic before/after among {sorted(ids - placed)}"])
        result.append([next(x for x in agents if x.agent_id == a) for a in layer])
        placed.update(layer)
    return result


def tool_problems(agent: AgentPlugin, registry) -> list[str]:
    """Declared tools ``server.tool`` that no registered MCP server defines."""
    problems = []
    for tool in agent.tools:
        server, _, name = tool.rpartition(".")
        if server not in registry.mcp_servers:
            problems.append(f"{agent.agent_id} declares tool {tool!r} of unknown server {server!r}")
        elif name not in registry.mcp_tools.get(server, {}):
            problems.append(f"{agent.agent_id} declares tool {tool!r}, which {server} lacks")
    return problems


def check(spec: WorkflowSpec, registry, enabled: Iterable[str] = ()) -> list[str]:
    problems = []
    node_ids = [node.node_id for node in spec.nodes]
    if len(node_ids) != len(set(node_ids)):
        problems.append("duplicate node ids")
    points = {point.point_id: point for point in spec.extension_points}
    for point_id in points:
        if point_id not in node_ids:
            problems.append(f"extension point {point_id} has no pass-through node")
    for node in spec.nodes:
        if node.agent is not None and node.agent not in registry.agents:
            problems.append(f"node {node.node_id} runs unknown agent {node.agent!r}")
        elif node.agent is not None and not registry.agents[node.agent].core:
            problems.append(f"node {node.node_id} runs a plugin agent as a core node")
        elif node.agent is not None:
            problems.extend(tool_problems(registry.agents[node.agent], registry))
    known = {"__start__", "__end__", *node_ids}
    for source, target in spec.edges:
        if source not in known or target not in known:
            problems.append(f"edge {source} -> {target} names an unknown node")
    for route in spec.routes:
        if route.source not in node_ids:
            problems.append(f"route from unknown node {route.source}")
        for target in route.targets:
            if target not in known:
                problems.append(f"route {route.source} targets unknown node {target}")
    state_keys = set(getattr(spec.state_schema, "__annotations__", {}))
    by_point = extension_agents(spec, registry, enabled)
    produced: dict[str, set[str]] = {}
    for agent in registry.agents.values():
        point = agent.extends.get(spec.workflow_id)
        if point is not None and point not in points:
            problems.append(f"agent {agent.agent_id} joins unknown extension point {point!r}")
    order = [node_id for node_id in node_ids if node_id in points]
    for point_id in order:
        agents = by_point.get(point_id, [])
        try:
            ordered = layers(agents)
        except WorkflowError as exc:
            problems.extend(exc.problems)
            continue
        available = set(points[point_id].available) | set(IDENTITY_KEYS)
        for layer in ordered:
            for agent in layer:
                for key in agent.consumes:
                    if key.startswith(EXTENSION_PREFIX):
                        owner, _, name = key.removeprefix(EXTENSION_PREFIX).partition("/")
                        if name not in produced.get(owner, set()):
                            problems.append(
                                f"{agent.agent_id} reads {key}, which no earlier agent produces"
                            )
                    elif key not in state_keys:
                        problems.append(f"{agent.agent_id} reads unknown state key {key!r}")
                    elif key not in available:
                        problems.append(
                            f"{agent.agent_id} reads {key!r}, not guaranteed at {point_id}"
                        )
                for key in agent.produces:
                    if key in spec.core_keys or key in state_keys:
                        problems.append(
                            f"{agent.agent_id} writes core state key {key!r}; plugin agents "
                            "write only to their own namespace"
                        )
                problems.extend(tool_problems(agent, registry))
                if not 1 <= agent.retries <= 3:
                    problems.append(f"{agent.agent_id}: retries must be between 1 and 3")
                if agent.max_iterations < 1 or agent.timeout_s <= 0:
                    problems.append(f"{agent.agent_id}: bad iteration or timeout limit")
            for agent in layer:
                produced[agent.agent_id] = set(agent.produces)
    return problems


def plugin_view(agent: AgentPlugin, state: dict) -> dict:
    view = {key: state.get(key) for key in IDENTITY_KEYS if key in state}
    extensions = state.get("extensions") or {}
    for key in agent.consumes:
        if key.startswith(EXTENSION_PREFIX):
            owner, _, name = key.removeprefix(EXTENSION_PREFIX).partition("/")
            view[key] = (extensions.get(owner) or {}).get(name)
        else:
            view[key] = state.get(key)
    return view


def plugin_node(agent: AgentPlugin, built):
    """The node of a plugin agent: its view in, its own namespace out, bounded in time."""

    def call(view):
        if agent.input_schema is not None:
            agent.input_schema.model_validate(view)
        if hasattr(built, "invoke"):
            data = agent.subgraph_input(view) if agent.subgraph_input else view
            out = built.invoke(data, config={"recursion_limit": 25 * agent.max_iterations})
            out = agent.subgraph_output(out) if agent.subgraph_output else out
        else:
            out = built(view)
        out = dict(out or {})
        unknown = set(out) - set(agent.produces)
        if unknown:
            raise AgentFailure([f"{agent.agent_id} wrote undeclared keys {sorted(unknown)}"])
        if agent.output_schema is not None:
            agent.output_schema.model_validate(out)
        return out

    def run(state):
        view = plugin_view(agent, state)
        errors = []
        for _ in range(agent.retries):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                # The node's run, node and attempt follow the agent into the worker thread,
                # so its LLM and tool calls are audited under it.
                future = pool.submit(contextvars.copy_context().run, call, view)
                try:
                    return {"extensions": {agent.agent_id: future.result(agent.timeout_s)}}
                except concurrent.futures.TimeoutError:
                    errors.append(f"{agent.agent_id} exceeded {agent.timeout_s} s")
                except AgentFailure as exc:
                    errors.extend(exc.errors)
                except Exception as exc:  # noqa: BLE001 - a plugin failure is recorded
                    errors.append(f"{agent.agent_id}: {type(exc).__name__}: {exc}")
        # An optional researcher that fails leaves its failure in its namespace only.
        return {"extensions": {agent.agent_id: {"failed": True, "errors": errors}}}

    return run


def compile_workflow(
    spec: WorkflowSpec,
    registry,
    *,
    checkpointer,
    runtime,
    enabled: Iterable[str] = (),
    services=None,
    interrupt_before=None,
    llm=None,
    gateway=None,
):
    """``llm`` and ``gateway`` (the run's ``ToolGateway``) reach every agent through its
    ``AgentContext``; the gateway only as the tools the agent declared."""
    problems = check(spec, registry, enabled)
    if problems:
        raise WorkflowError(problems)

    def context(agent, services):
        return AgentContext(
            agent=agent,
            services=services,
            registry=registry,
            llm=llm,
            tools=DeclaredTools(gateway, agent.agent_id, agent.tools),
        )

    builder = StateGraph(spec.state_schema, input_schema=spec.input_schema)
    for node in spec.nodes:
        if node.agent is None:
            builder.add_node(node.node_id, _pass)
            continue
        agent = registry.agents[node.agent]
        fn = agent.build(context(agent, runtime))
        consumes = agent.consumes

        def inputs(state, consumes=consumes):
            return {key: state.get(key) for key in consumes} if consumes else None

        builder.add_node(
            node.node_id,
            journaled(
                node.node_id,
                fn,
                runtime,
                version=agent.version,
                inputs=inputs if consumes else None,
                branch=node.branch,
            ),
        )
    replaced = {}
    points = {point.point_id for point in spec.extension_points}
    for point_id, agents in extension_agents(spec, registry, enabled).items():
        if not agents or point_id not in points:
            continue
        ordered = layers(agents)
        for layer in ordered:
            for agent in layer:
                built = agent.build(context(agent, services or runtime))
                builder.add_node(
                    agent.agent_id,
                    journaled(
                        agent.agent_id,
                        plugin_node(agent, built),
                        runtime,
                        version=agent.version,
                        inputs=lambda state, agent=agent: plugin_view(agent, state),
                    ),
                )
        replaced[point_id] = [[a.agent_id for a in layer] for layer in ordered]
    for source, target in spec.edges:
        source_id = START if source == "__start__" else source
        target_id = END if target == "__end__" else target
        chain = replaced.get(source)
        if chain:
            # point -> layer 1 -> ... -> layer n -> target; a layer waits for all its agents.
            for node_id in chain[0]:
                builder.add_edge(source_id, node_id)
            for previous, following in zip(chain, chain[1:], strict=False):
                for node_id in following:
                    builder.add_edge(previous if len(previous) > 1 else previous[0], node_id)
            last = chain[-1]
            builder.add_edge(last if len(last) > 1 else last[0], target_id)
        else:
            builder.add_edge(source_id, target_id)
    for route in spec.routes:
        builder.add_conditional_edges(
            route.source,
            route.router,
            [END if t == "__end__" else t for t in route.targets],
        )
    return builder.compile(checkpointer=checkpointer)


def _pass(state):
    return {}


def describe(spec: WorkflowSpec, registry, enabled: Iterable[str] = ()) -> dict:
    """The workflow as the screens and the catalog show it: stages, nodes and agents."""
    by_point = extension_agents(spec, registry, enabled)
    labels = {}
    for node in spec.nodes:
        if node.agent is not None:
            labels[node.node_id] = registry.agents[node.agent].label
        else:
            point = next(p for p in spec.extension_points if p.point_id == node.node_id)
            labels[node.node_id] = point.label
    stages = []
    for stage in spec.stages:
        nodes = []
        for node_id in stage.nodes:
            node = spec.node(node_id)
            if node.agent is None:
                for layer in layers(by_point.get(node_id, [])):
                    for agent in layer:
                        nodes.append(
                            {
                                "node": agent.agent_id,
                                "label": agent.label,
                                "plugin": True,
                                "version": agent.version,
                                "point": node_id,
                            }
                        )
                continue
            nodes.append(
                {
                    "node": node_id,
                    "label": labels[node_id],
                    "human": node.human,
                    "branch": node.branch,
                    "plugin": False,
                    "version": registry.agents[node.agent].version,
                }
            )
        stages.append({"stage_id": stage.stage_id, "title": stage.title, "nodes": nodes})
    return {
        "workflow_id": spec.workflow_id,
        "version": spec.version,
        "label": spec.label,
        "description": spec.description,
        "stages": stages,
        "extension_points": [
            {
                "point_id": point.point_id,
                "label": point.label,
                "agents": [
                    a.agent_id for layer in layers(by_point.get(point.point_id, [])) for a in layer
                ],
            }
            for point in spec.extension_points
        ],
    }
