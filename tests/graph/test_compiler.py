"""msa.graph.compiler: layers(), check(), extension_agents(), WorkflowSpec.node(), describe()."""

from typing import TypedDict

import pytest

from msa.graph.compiler import WorkflowError, check, describe, extension_agents, layers
from msa.platform.registry import Registry
from msa.plugin_sdk.agent import AgentPlugin, ExtensionPoint, NodeSpec, StageSpec, WorkflowSpec


def agent(
    agent_id,
    *,
    extends=None,
    consumes=(),
    produces=(),
    before=(),
    after=(),
    core=False,
    retries=1,
    max_iterations=1,
    timeout_s=120.0,
    enabled_by_default=True,
):
    return AgentPlugin(
        agent_id=agent_id,
        version="1.0.0",
        label=agent_id,
        build=lambda ctx: (lambda view: {}),
        extends=extends or {},
        consumes=consumes,
        produces=produces,
        before=before,
        after=after,
        core=core,
        retries=retries,
        max_iterations=max_iterations,
        timeout_s=timeout_s,
        enabled_by_default=enabled_by_default,
    )


class State(TypedDict, total=False):
    run_id: str
    core_value: str


def spec(
    *, nodes=None, edges=None, extension_points=None, routes=None, core_keys=None, stages=None
):
    return WorkflowSpec(
        workflow_id="wf1",
        version="1.0.0",
        label="WF",
        state_schema=State,
        input_schema=State,
        nodes=nodes
        if nodes is not None
        else (NodeSpec(node_id="point_a", agent=None, stage="s1"),),
        edges=edges if edges is not None else (("__start__", "point_a"), ("point_a", "__end__")),
        extension_points=extension_points
        if extension_points is not None
        else (ExtensionPoint(point_id="point_a", label="A", available=("core_value",)),),
        routes=routes or (),
        core_keys=core_keys or frozenset({"core_value"}),
        stages=stages or (),
    )


def registry_of(*agents):
    return Registry(agents={a.agent_id: a for a in agents})


# -- layers() -----------------------------------------------------------------------------


def test_layers_agents_with_no_relation_share_one_layer():
    a, b = agent("a", extends={"wf1": "point_a"}), agent("b", extends={"wf1": "point_a"})
    result = layers([a, b])
    assert len(result) == 1
    assert {x.agent_id for x in result[0]} == {"a", "b"}


def test_layers_after_orders_into_two_layers():
    a = agent("a", extends={"wf1": "point_a"})
    b = agent("b", extends={"wf1": "point_a"}, after=("a",))
    result = layers([a, b])
    assert [{x.agent_id for x in layer} for layer in result] == [{"a"}, {"b"}]


def test_layers_before_orders_into_two_layers():
    a = agent("a", extends={"wf1": "point_a"}, before=("b",))
    b = agent("b", extends={"wf1": "point_a"})
    result = layers([a, b])
    assert [{x.agent_id for x in layer} for layer in result] == [{"a"}, {"b"}]


def test_layers_raises_on_unknown_after_dependency():
    a = agent("a", extends={"wf1": "point_a"}, after=("nope",))
    with pytest.raises(WorkflowError, match="runs after unknown agent"):
        layers([a])


def test_layers_raises_on_unknown_before_dependency():
    a = agent("a", extends={"wf1": "point_a"}, before=("nope",))
    with pytest.raises(WorkflowError, match="runs before unknown agent"):
        layers([a])


def test_layers_raises_on_a_cycle():
    a = agent("a", extends={"wf1": "point_a"}, after=("b",))
    b = agent("b", extends={"wf1": "point_a"}, after=("a",))
    with pytest.raises(WorkflowError, match="cyclic"):
        layers([a, b])


# -- extension_agents() --------------------------------------------------------------------


def test_extension_agents_groups_by_point_for_this_workflow():
    a = agent("a", extends={"wf1": "point_a"})
    other_workflow = agent("b", extends={"other": "point_a"})
    reg = registry_of(a, other_workflow)
    by_point = extension_agents(spec(), reg)
    assert [x.agent_id for x in by_point["point_a"]] == ["a"]


def test_extension_agents_skips_core_agents():
    core_agent = agent("core", extends={"wf1": "point_a"}, core=True)
    reg = registry_of(core_agent)
    by_point = extension_agents(spec(), reg)
    assert by_point["point_a"] == []


def test_extension_agents_skips_disabled_non_default_agents():
    off = agent("off", extends={"wf1": "point_a"}, enabled_by_default=False)
    reg = registry_of(off)
    assert extension_agents(spec(), reg)["point_a"] == []
    enabled = extension_agents(spec(), reg, enabled={"off"})["point_a"]
    assert [x.agent_id for x in enabled] == ["off"]


# -- check() --------------------------------------------------------------------------------


def test_check_passes_for_a_minimal_valid_workflow():
    a = agent("a", extends={"wf1": "point_a"}, consumes=("core_value",), produces=("out",))
    reg = registry_of(a)
    assert check(spec(), reg) == []


def test_check_reports_duplicate_node_ids():
    nodes = (
        NodeSpec(node_id="point_a", agent=None, stage="s1"),
        NodeSpec(node_id="point_a", agent=None, stage="s1"),
    )
    problems = check(spec(nodes=nodes), registry_of())
    assert "duplicate node ids" in problems


def test_check_reports_extension_point_without_a_node():
    points = (ExtensionPoint(point_id="missing_node", label="M"),)
    problems = check(spec(extension_points=points), registry_of())
    assert any("has no pass-through node" in p for p in problems)


def test_check_reports_edge_to_unknown_node():
    edges = (("__start__", "point_a"), ("point_a", "nowhere"))
    problems = check(spec(edges=edges), registry_of())
    assert any("names an unknown node" in p for p in problems)


def test_check_reports_route_from_unknown_node():
    from msa.plugin_sdk.agent import Route

    routes = (Route(source="nowhere", router=lambda s: "point_a", targets=("point_a",)),)
    problems = check(spec(routes=routes), registry_of())
    assert any("route from unknown node" in p for p in problems)


def test_check_reports_route_targeting_unknown_node():
    from msa.plugin_sdk.agent import Route

    routes = (Route(source="point_a", router=lambda s: "nowhere", targets=("nowhere",)),)
    problems = check(spec(routes=routes), registry_of())
    assert any("targets unknown node" in p for p in problems)


def test_check_reports_node_running_unknown_agent():
    nodes = (NodeSpec(node_id="core_node", agent="ghost", stage="s1"),)
    edges = (("__start__", "core_node"), ("core_node", "__end__"))
    problems = check(spec(nodes=nodes, edges=edges, extension_points=()), registry_of())
    assert any("runs unknown agent" in p for p in problems)


def test_check_reports_node_running_a_plugin_agent_as_a_core_node():
    plugin_agent = agent("not_core")
    nodes = (NodeSpec(node_id="core_node", agent="not_core", stage="s1"),)
    edges = (("__start__", "core_node"), ("core_node", "__end__"))
    problems = check(spec(nodes=nodes, edges=edges, extension_points=()), registry_of(plugin_agent))
    assert any("runs a plugin agent as a core node" in p for p in problems)


def test_check_reports_agent_reading_undeclared_state_key():
    a = agent("a", extends={"wf1": "point_a"}, consumes=("no_such_key",))
    problems = check(spec(), registry_of(a))
    assert any("reads unknown state key" in p for p in problems)


def test_check_reports_agent_reading_state_key_not_available_at_point():
    points = (ExtensionPoint(point_id="point_a", label="A", available=()),)
    a = agent("a", extends={"wf1": "point_a"}, consumes=("core_value",))
    problems = check(spec(extension_points=points), registry_of(a))
    assert any("not guaranteed at point_a" in p for p in problems)


def test_check_reports_agent_reading_ext_key_with_no_earlier_producer():
    a = agent("a", extends={"wf1": "point_a"}, consumes=("ext:other/value",))
    problems = check(spec(), registry_of(a))
    assert any("which no earlier agent produces" in p for p in problems)


def test_check_accepts_ext_key_produced_by_an_earlier_layer():
    a = agent("a", extends={"wf1": "point_a"}, produces=("value",))
    b = agent("b", extends={"wf1": "point_a"}, after=("a",), consumes=("ext:a/value",))
    assert check(spec(), registry_of(a, b)) == []


def test_check_reports_agent_writing_a_core_state_key():
    a = agent("a", extends={"wf1": "point_a"}, produces=("core_value",))
    problems = check(spec(), registry_of(a))
    assert any("writes core state key" in p for p in problems)


def test_check_reports_retries_out_of_range():
    a = agent("a", extends={"wf1": "point_a"}, retries=5)
    problems = check(spec(), registry_of(a))
    assert any("retries must be between 1 and 3" in p for p in problems)


def test_check_reports_bad_iteration_or_timeout():
    a = agent("a", extends={"wf1": "point_a"}, max_iterations=0)
    problems = check(spec(), registry_of(a))
    assert any("bad iteration or timeout limit" in p for p in problems)


def test_check_reports_agent_joining_unknown_extension_point():
    a = agent("a", extends={"wf1": "ghost_point"})
    problems = check(spec(), registry_of(a))
    assert any("joins unknown extension point" in p for p in problems)


# -- WorkflowSpec.node() ----------------------------------------------------------------------


def test_workflow_spec_node_finds_the_matching_node():
    s = spec()
    assert s.node("point_a").node_id == "point_a"


def test_workflow_spec_node_raises_for_unknown_id():
    s = spec()
    with pytest.raises(StopIteration):
        s.node("nowhere")


# -- describe() -----------------------------------------------------------------------------


def test_describe_lists_plugin_agents_of_an_extension_point_by_stage():
    a = agent("a", extends={"wf1": "point_a"}, consumes=("core_value",), produces=("out",))
    reg = registry_of(a)
    described = describe(
        spec(stages=(StageSpec(stage_id="s1", title="Stage 1", nodes=("point_a",)),)), reg
    )
    assert described["workflow_id"] == "wf1"
    stage_nodes = described["stages"][0]["nodes"]
    assert stage_nodes == [
        {"node": "a", "label": "a", "plugin": True, "version": "1.0.0", "point": "point_a"}
    ]
    assert described["extension_points"][0]["agents"] == ["a"]
