"""Plugin MCP servers: registry validation, ``ToolGateway`` and the UI manifest's agents.

The real ``research.notes`` server (``src/msa/plugins/research``) is the fixture: it declares
one tool, ``slice_digest``, with no data access of its own.
"""

import pytest

from msa.graph import activity
from msa.cli.plugin import ui_manifest
from msa.mcp.gateway import ToolGateway
from msa.platform.registry import PluginError, build, registry
from msa.plugin_sdk import McpServerSpec, Plugin

# -- the real registry: core servers and the research plugin's own -----------------------


def test_registry_lists_core_servers_and_the_research_plugins_server():
    reg = registry()
    assert {"portfolio", "models", "runs", "research.notes"} <= set(reg.mcp_servers)
    assert "resolve_inputs" in reg.mcp_tools["portfolio"]
    assert "run_model" in reg.mcp_tools["models"]
    assert "slice_digest" in reg.mcp_tools["research.notes"]


def test_ui_manifest_lists_the_research_agents_and_no_core_agent():
    manifest = ui_manifest()
    agents = manifest["agents"]
    assert agents["research.concentration"] == "research"
    assert agents["research.brief"] == "research"
    assert agents["research.digest"] == "research"
    assert not any(agent_id.startswith("core.") for agent_id in agents)


# -- build() problems around a plugin's declared MCP server ------------------------------


def _server_plugin(plugin_id, name, register, **overrides):
    values = dict(
        plugin_id=plugin_id,
        version="1.0.0",
        sdk=">=1.0,<2.0",
        label="Extra",
        mcp_servers=(McpServerSpec(name, register),),
    )
    values.update(overrides)
    return Plugin(**values)


def test_build_rejects_an_unprefixed_server_name():
    def register(tool, services):
        @tool
        def do_thing(x: int, audit) -> int:
            return x

    plugin = _server_plugin("extra", "badserver", register)
    with pytest.raises(PluginError, match="must start with 'extra.'"):
        build([plugin])


def test_build_rejects_a_tool_without_an_audit_parameter():
    def register(tool, services):
        @tool
        def do_thing(x: int) -> int:
            return x

    plugin = _server_plugin("extra", "extra.srv", register)
    with pytest.raises(PluginError, match="has no `audit` parameter"):
        build([plugin])


def test_build_rejects_a_register_that_raises():
    def register(tool, services):
        raise RuntimeError("kaboom")

    plugin = _server_plugin("extra", "extra.srv", register)
    with pytest.raises(PluginError, match="cannot list its tools"):
        build([plugin])


def test_build_rejects_a_server_with_no_tools():
    def register(tool, services):
        pass

    plugin = _server_plugin("extra", "extra.srv", register)
    with pytest.raises(PluginError, match="defines no tools"):
        build([plugin])


def test_build_rejects_a_duplicate_server_name():
    def register(tool, services):
        @tool
        def do_thing(x: int, audit) -> int:
            return x

    a = _server_plugin("extraa", "extraa.srv", register)
    b = _server_plugin("extrab", "extraa.srv", register)
    with pytest.raises(PluginError, match="is already declared by extraa"):
        build([a, b])


# -- ToolGateway on the real research.notes server ----------------------------------------


class FakeDB:
    def __init__(self):
        self.calls = []

    def get(self, scope, kind, key):
        return {"run_id": key["run_id"]}

    def audit(self, scope, actor, action, *, run_id, node, attempt, tool, standalone, details):
        self.calls.append(
            {
                "scope": scope,
                "actor": actor,
                "action": action,
                "run_id": run_id,
                "node": node,
                "attempt": attempt,
                "tool": tool,
                "standalone": standalone,
                "details": details,
            }
        )


class FakeServices:
    def __init__(self):
        self.db = FakeDB()
        self.scope = "production"
        self.actor = "tester"


def test_tool_gateway_lists_the_research_notes_tool():
    gateway = ToolGateway(FakeServices())
    tools = {item["name"] for item in gateway.tools("research.notes")}
    assert "slice_digest" in tools


def test_a_real_audited_call_reaches_the_research_tool_and_is_recorded():
    services = FakeServices()
    gateway = ToolGateway(services)
    slices = [
        {
            "slice_id": "credit.loss",
            "contributions": [
                {"position_id": "P1", "expected_shortfall_contribution": 3.0},
                {"position_id": "P2", "expected_shortfall_contribution": 1.0},
            ],
        }
    ]
    with activity.node_call("RUN1", "research.digest", 1):
        result = gateway.call_as(
            "research.notes", "slice_digest", {"slices": slices}, initiator="workflow"
        )
    assert result == [
        {"slice_id": "credit.loss", "positions": 2, "top_share": 0.75, "herfindahl": 0.625}
    ]
    (call,) = services.db.calls
    assert call["tool"] == "mcp-research.notes.slice_digest"
    assert call["node"] == "research.digest"
    assert call["run_id"] == "RUN1"
    assert call["details"]["initiator"] == "workflow"
