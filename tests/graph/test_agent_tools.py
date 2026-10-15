"""``DeclaredTools`` (msa.mcp.tools), the compiler's tool checks and how the run's
``llm``/``gateway`` reach an agent plugin's context, down to its node's worker thread."""

import json

import pytest

from msa.graph import activity, compiler
from msa.graph.checkpoint import build_checkpointer
from msa.graph.interrupts import start_run
from msa.graph.workflow import build_graph
from msa.mcp.tools import DeclaredTools, ToolError, ToolNotDeclared
from msa.platform.registry import installed
from msa.plugin_sdk.agent import AgentPlugin
from msa.plugin_sdk.plugin import Plugin

from ..support import agents as default_agents
from ..support import confirm, run_input, stop

TOOL = "research.notes.slice_digest"


class FakeGateway:
    def __init__(self):
        self.calls = []

    def call_as(self, server, tool, arguments, *, initiator, call_id=None):
        self.calls.append((server, tool, arguments, initiator, call_id))
        return {"server": server, "tool": tool}

    def tools(self, server):
        return [
            {
                "name": "slice_digest",
                "description": "Digest.",
                "input_schema": {
                    "properties": {
                        "slices": {"type": "array"},
                        "audit": {"type": "object"},
                    },
                    "required": ["slices", "audit"],
                },
            }
        ]


# -- DeclaredTools -------------------------------------------------------------------------


def test_call_routes_server_dot_tool_to_the_gateway_with_workflow_as_initiator():
    gateway = FakeGateway()
    declared = DeclaredTools(gateway, "research.digest", (TOOL,))
    result = declared.call(TOOL, slices=[1, 2])
    assert result == {"server": "research.notes", "tool": "slice_digest"}
    (call,) = gateway.calls
    assert call == ("research.notes", "slice_digest", {"slices": [1, 2]}, "workflow", None)


def test_call_as_accepts_the_double_underscore_function_name():
    gateway = FakeGateway()
    declared = DeclaredTools(gateway, "research.digest", (TOOL,))
    declared.call_as("research__notes__slice_digest", {"slices": []}, initiator="llm", call_id="c1")
    (call,) = gateway.calls
    assert call == ("research.notes", "slice_digest", {"slices": []}, "llm", "c1")


def test_an_undeclared_tool_raises_tool_not_declared():
    declared = DeclaredTools(FakeGateway(), "research.digest", (TOOL,))
    with pytest.raises(ToolNotDeclared, match="research.digest"):
        declared.call("research.notes.other_tool")


def test_no_gateway_raises_tool_error_for_a_declared_tool():
    declared = DeclaredTools(None, "research.digest", (TOOL,))
    with pytest.raises(ToolError, match="no MCP gateway in this run"):
        declared.call(TOOL)


def test_functions_strips_audit_from_properties_and_required():
    declared = DeclaredTools(FakeGateway(), "research.digest", (TOOL,))
    (spec,) = declared.functions()
    assert spec["function"]["name"] == "research__notes__slice_digest"
    properties = spec["function"]["parameters"]["properties"]
    required = spec["function"]["parameters"]["required"]
    assert "audit" not in properties
    assert "audit" not in required
    assert required == ["slices"]


def test_functions_is_empty_without_a_gateway():
    declared = DeclaredTools(None, "research.digest", (TOOL,))
    assert declared.functions() == []


# -- compiler.check(): tools of unknown servers or missing tools --------------------------


def _tool_agent(agent_id, tools):
    return AgentPlugin(
        agent_id=agent_id,
        version="1.0.0",
        label="Probe",
        build=lambda context: (lambda view: {}),
        extends={"stress_test": "after_calculation"},
        tools=tools,
        enabled_by_default=False,
    )


def test_check_reports_a_tool_of_an_unknown_server_and_a_missing_tool_of_a_known_server():
    plugin = Plugin(
        plugin_id="toolcheck",
        version="1.0.0",
        sdk=">=1.0,<2.0",
        label="Tool check",
        agents=(
            _tool_agent("toolcheck.unknown_server", ("nope.server.tool",)),
            _tool_agent("toolcheck.missing_tool", ("research.notes.no_such_tool",)),
        ),
    )
    with installed(plugin) as reg:
        problems = compiler.check(
            reg.workflows["stress_test"],
            reg,
            ["toolcheck.unknown_server", "toolcheck.missing_tool"],
        )
    assert any(
        "toolcheck.unknown_server declares tool 'nope.server.tool' of unknown server "
        "'nope.server'" in p
        for p in problems
    )
    assert any(
        "toolcheck.missing_tool declares tool 'research.notes.no_such_tool', which "
        "research.notes lacks" in p
        for p in problems
    )


# -- build_graph(..., llm=..., gateway=...) reaches the agent's AgentContext ---------------


def test_build_graph_passes_llm_and_gateway_into_a_plugin_agents_context():
    captured = []

    def build(context):
        captured.append(context)
        return lambda view: {}

    agent = AgentPlugin(
        agent_id="ctxprobe.agent",
        version="1.0.0",
        label="Probe",
        build=build,
        extends={"stress_test": "after_calculation"},
        tools=(TOOL,),
        enabled_by_default=False,
    )
    plugin = Plugin(
        plugin_id="ctxprobe", version="1.0.0", sdk=">=1.0,<2.0", label="x", agents=(agent,)
    )
    llm_sentinel = object()
    fake_gateway = FakeGateway()
    with installed(plugin) as reg, build_checkpointer() as saver:
        build_graph(
            saver,
            agents=default_agents(calculate=False),
            registry=reg,
            options=reg.run_options("demo"),
            enabled=("ctxprobe.agent",),
            llm=llm_sentinel,
            gateway=fake_gateway,
        )
    (context,) = captured
    assert context.llm is llm_sentinel
    assert context.tools.gateway is fake_gateway
    assert context.tools.declared == (TOOL,)


def test_a_plugin_agents_node_sees_its_agent_id_in_the_activity_context(graph_factory):
    def build(context):
        def node(view):
            current = activity.current() or {}
            return {"seen_node": current.get("node")}

        return node

    agent = AgentPlugin(
        agent_id="activityprobe.agent",
        version="1.0.0",
        label="Probe",
        build=build,
        extends={"stress_test": "after_calculation"},
        produces=("seen_node",),
        enabled_by_default=False,
    )
    plugin = Plugin(
        plugin_id="activityprobe", version="1.0.0", sdk=">=1.0,<2.0", label="x", agents=(agent,)
    )
    with installed(plugin) as reg:
        graph, _journal = graph_factory(
            agents=default_agents(calculate=True),
            enabled=("activityprobe.agent",),
            registry_=reg,
        )
        start_run(graph, run_input("activity-probe"))
        state = confirm(graph, "activity-probe")
    assert state["extensions"]["activityprobe.agent"]["seen_node"] == "activityprobe.agent"


# -- research.digest without a gateway fails into its own namespace only ------------------


def test_research_digest_without_a_gateway_fails_into_its_namespace_and_leaves_results_unchanged(
    graph_factory,
):
    plain, _ = graph_factory(agents=default_agents(calculate=True))
    start_run(plain, run_input("digest-plain"))
    base = confirm(plain, "digest-plain")

    graph, journal = graph_factory(
        agents=default_agents(calculate=True), enabled=("research.digest",)
    )
    start_run(graph, run_input("digest-no-gateway"))
    state = confirm(graph, "digest-no-gateway")

    assert stop(graph, "digest-no-gateway")["kind"] == "human_approval"
    ext = state["extensions"]["research.digest"]
    assert ext["failed"] is True
    assert any("no MCP gateway" in error for error in ext["errors"])
    for key in ("sorted_results", "portfolio_result", "report"):
        text = json.dumps(base[key], sort_keys=True)
        same = text.replace('"digest-plain"', '"digest-no-gateway"')
        assert json.dumps(state[key], sort_keys=True) == same, key
    nodes = {row["node"] for row in journal.list_node_results("digest-no-gateway")}
    assert "research.digest" in nodes
