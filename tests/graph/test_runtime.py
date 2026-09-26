"""msa.graph.runtime: journaled() replay identity and InputsChanged."""

import pytest

from msa.agents.base import AgentFailure
from msa.db.repositories.runs import MemoryRunRepository
from msa.graph.checkpoint import run_config
from msa.graph.runtime import InputsChanged, NodeContext, journaled


def context(repository=None):
    return NodeContext(
        agents=None,
        repository=repository or MemoryRunRepository(),
        validate=None,
    )


def state(run_id="R1", **extra):
    return {"run_id": run_id, **extra}


def test_journaled_runs_the_node_function_once_and_records_it():
    calls = []

    def fn(view):
        calls.append(view)
        return {"value": 1}

    ctx = context()
    node = journaled("mynode", fn, ctx)
    result = node(state(), run_config("R1"))
    assert result["value"] == 1
    assert result["trace"] == ["mynode"]
    assert len(calls) == 1


def test_journaled_replays_the_recorded_result_without_calling_fn_again():
    call_count = {"n": 0}

    def fn(view):
        call_count["n"] += 1
        return {"value": call_count["n"]}

    ctx = context()
    node = journaled("mynode", fn, ctx)
    first = node(state(), run_config("R1"))
    second = node(state(), run_config("R1"))
    assert first == second
    assert call_count["n"] == 1


def test_journaled_recomputes_after_a_graph_revision_bump():
    # For an ordinary node (not causal_agent/validate_causal) the attempt is graph_revision+1,
    # so a revision bump is a new journal entry and the node runs again.
    call_count = {"n": 0}

    def fn(view):
        call_count["n"] += 1
        return {"value": call_count["n"]}

    ctx = context()
    node = journaled("mynode", fn, ctx)
    node(state(), run_config("R1"))
    node(state(graph_revision=1), run_config("R1"))
    assert call_count["n"] == 2


def test_journaled_raises_inputs_changed_when_recorded_inputs_differ():
    def fn(view):
        return {"value": view.get("core_value")}

    ctx = context()
    node = journaled("mynode", fn, ctx, inputs=lambda s: {"core_value": s.get("core_value")})
    node(state(core_value="a"), run_config("R1"))
    with pytest.raises(InputsChanged):
        node(state(core_value="b"), run_config("R1"))


def test_journaled_replays_when_recorded_inputs_are_unchanged():
    calls = []

    def fn(view):
        calls.append(1)
        return {"value": view.get("core_value")}

    ctx = context()
    node = journaled("mynode", fn, ctx, inputs=lambda s: {"core_value": s.get("core_value")})
    node(state(core_value="a"), run_config("R1"))
    node(state(core_value="a"), run_config("R1"))
    assert len(calls) == 1


def test_journaled_raises_value_error_on_thread_id_mismatch():
    ctx = context()
    node = journaled("mynode", lambda view: {}, ctx)
    with pytest.raises(ValueError, match="thread_id does not match run_id"):
        node(state(run_id="R1"), run_config("OTHER"))


def test_journaled_converts_agent_failure_into_needs_review_update():
    def fn(view):
        raise AgentFailure(["boom"])

    ctx = context()
    node = journaled("mynode", fn, ctx)
    result = node(state(), run_config("R1"))
    assert result["status"] == "needs_review"
    assert result["errors"] == ["boom"]
    assert result["published"] is False


def test_journaled_branch_gives_a_separate_journal_entry_per_branch_value():
    calls = []

    def fn(view):
        calls.append(view.get("asset_id"))
        return {"value": view.get("asset_id")}

    ctx = context()
    node = journaled("quant_agent", fn, ctx, branch="asset_id")
    a = node(state(asset_id="A"), run_config("R1"))
    b = node(state(asset_id="B"), run_config("R1"))
    assert a["value"] == "A"
    assert b["value"] == "B"
    assert calls == ["A", "B"]
