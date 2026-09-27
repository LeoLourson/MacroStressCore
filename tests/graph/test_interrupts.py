"""msa.graph.interrupts: drive streams every state, marks interrupts, and resumes runs."""

import operator
from typing import Annotated, TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from msa.graph.checkpoint import run_config
from msa.graph.interrupts import drive, pending_interrupt, resume_run, start_run


class TinyState(TypedDict, total=False):
    run_id: str
    value: int
    trace: Annotated[list, operator.add]


def increment(state):
    return {"value": state.get("value", 0) + 1, "trace": ["increment"]}


def times_ten(state):
    return {"value": state["value"] * 10, "trace": ["times_ten"]}


def ask_and_add(state):
    reply = interrupt({"kind": "question"})
    return {"value": state["value"] + reply["add"], "trace": ["ask"]}


def compile_graph(saver, *, ask=False):
    builder = StateGraph(TinyState)
    builder.add_node("increment", increment)
    builder.add_edge(START, "increment")
    if ask:
        builder.add_node("ask", ask_and_add)
        builder.add_edge("increment", "ask")
        builder.add_edge("ask", END)
    else:
        builder.add_node("times_ten", times_ten)
        builder.add_edge("increment", "times_ten")
        builder.add_edge("times_ten", END)
    return builder.compile(checkpointer=saver)


@pytest.fixture
def saver():
    with InMemorySaver() as checkpointer:
        yield checkpointer


def test_drive_matches_invoke_and_reports_every_intermediate_state(saver):
    graph = compile_graph(saver)
    seen = []

    def step(state, upcoming):
        seen.append(state)

    result = drive(graph, {"run_id": "d1", "value": 1}, run_config("d1"), step)
    expected = graph.invoke({"value": 1}, run_config("invoke"))
    assert result["value"] == expected["value"] == 20
    assert result["trace"] == expected["trace"] == ["increment", "times_ten"]
    values = [state["value"] for state in seen]
    assert values[-1] == 20
    assert 2 in values  # the state between the two nodes was handed to on_step
    assert len(values) >= 2


def test_drive_marks_an_interrupt_and_resume_run_continues_it(saver):
    graph = compile_graph(saver, ask=True)
    first = drive(graph, {"run_id": "r1", "value": 1}, run_config("r1"))
    assert "__interrupt__" in first
    assert first["value"] == 2
    assert [item["payload"] for item in pending_interrupt(graph, "r1")] == [{"kind": "question"}]
    seen = []
    resumed = resume_run(graph, "r1", {"add": 41}, lambda state, upcoming: seen.append(state))
    assert resumed["value"] == 43
    assert "__interrupt__" not in resumed
    assert seen and seen[-1]["value"] == 43


def test_start_run_refuses_an_existing_run_id(saver):
    graph = compile_graph(saver)
    assert start_run(graph, {"run_id": "r1", "value": 1})["value"] == 20
    with pytest.raises(ValueError, match="already exists"):
        start_run(graph, {"run_id": "r1", "value": 1})


class RetryState(TypedDict, total=False):
    run_id: str
    attempts: int
    trace: Annotated[list, operator.add]


def work(state):
    return {"trace": ["work"]}


def retry(state):
    return {"attempts": state.get("attempts", 0) + 1, "trace": ["retry"]}


def route(state):
    return "retry" if state.get("attempts", 0) == 0 else "done"


def compile_retry_graph(saver):
    builder = StateGraph(RetryState)
    builder.add_node("work", work)
    builder.add_node("retry", retry)
    builder.add_edge(START, "work")
    builder.add_conditional_edges("work", route, {"retry": "retry", "done": END})
    builder.add_edge("retry", "work")
    return builder.compile(checkpointer=saver)


def spread(state):
    return {"trace": ["spread"]}


def fan_out(state):
    return [Send("branch", {}), Send("branch", {})]


def branch(state):
    return {"trace": ["branch"]}


def compile_fan_graph(saver):
    builder = StateGraph(TinyState)
    builder.add_node("spread", spread)
    builder.add_node("branch", branch)
    builder.add_edge(START, "spread")
    builder.add_conditional_edges("spread", fan_out)
    builder.add_edge("branch", END)
    return builder.compile(checkpointer=saver)


def test_drive_reports_the_node_each_checkpoint_starts_next(saver):
    graph = compile_retry_graph(saver)
    seen = []
    result = drive(
        graph,
        {"run_id": "retry", "attempts": 0},
        run_config("retry"),
        lambda state, upcoming: seen.append(upcoming),
    )
    # The first checkpoint of a new run (next == ["__start__"]) is not reported.
    assert ["__start__"] not in seen
    # After a conditional route the graph starts the route's target next.
    assert seen == [["work"], ["retry"], ["work"], []]
    assert result["attempts"] == 1


def test_drive_repeats_the_branch_node_of_a_send_fan_out(saver):
    graph = compile_fan_graph(saver)
    seen = []
    result = drive(
        graph,
        {"run_id": "fan", "value": 0},
        run_config("fan"),
        lambda state, upcoming: seen.append(upcoming),
    )
    assert seen[0] == ["spread"]
    assert seen[1] == ["branch", "branch"]
    assert seen[-1] == []
    assert result["trace"].count("branch") == 2
