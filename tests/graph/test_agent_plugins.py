"""Agent plugins in a run (plan, stage D): the example research plugin.

- it is off by default and joins a run only when named;
- its subgraph keeps its own state behind adapters and publishes only its namespace;
- the second agent reads the first one's output and runs after it;
- the run still stops for the risk manager, and the results and report do not change.
"""

import json

import pytest

from msa.graph.compiler import WorkflowError
from msa.graph.interrupts import start_run

from ..support import agents, confirm, run_input, stop

RESEARCH = ("research.concentration", "research.brief")


def test_the_research_agents_stay_out_unless_enabled(graph_factory):
    graph, journal = graph_factory(agents=agents(calculate=True))
    start_run(graph, run_input("plain"))
    state = confirm(graph, "plain")
    assert state.get("extensions", {}) == {}
    assert not {row["node"] for row in journal.list_node_results("plain")} & set(RESEARCH)


def test_enabled_research_agents_write_only_their_namespaces(graph_factory):
    plain, _ = graph_factory(agents=agents(calculate=True))
    start_run(plain, run_input("run-without-research"))
    base = confirm(plain, "run-without-research")

    graph, journal = graph_factory(agents=agents(calculate=True), enabled=RESEARCH)
    start_run(graph, run_input("research"))
    state = confirm(graph, "research")
    # The risk manager's decision is still ahead: no plugin passes a human stop.
    assert stop(graph, "research")["kind"] == "human_approval"
    notes = state["extensions"]["research.concentration"]["notes"]
    assert notes and {n["slice_id"] for n in notes} == {"credit.loss"}
    assert all(n["share_of_es95"] >= 0.25 for n in notes)
    brief = state["extensions"]["research.brief"]["brief"]
    assert len(brief) == len(notes) and all("ES95" in line for line in brief)
    # The subgraph's own state (its step counter, the slices it read) does not leak.
    assert set(state["extensions"]["research.concentration"]) == {"notes"}
    for key in ("sorted_results", "portfolio_result", "report"):
        same = json.dumps(base[key], sort_keys=True).replace('"run-without-research"', '"research"')
        assert json.dumps(state[key], sort_keys=True) == same, key
    nodes = [row["node"] for row in journal.list_node_results("research")]
    assert set(RESEARCH) <= set(nodes)


def test_an_agent_without_the_agent_it_reads_does_not_compile(graph_factory):
    with pytest.raises(WorkflowError, match="research.concentration"):
        graph_factory(agents=agents(calculate=True), enabled=("research.brief",))
