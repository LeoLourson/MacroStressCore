"""msa.graph.activity: the waiting LLM call of the current node, and the LLM client's use of it."""

import contextlib
import json

from msa.graph import activity
from msa.integrations.llm.client import LLMClient
from msa.integrations.llm.providers import Provider


def test_llm_waiting_registers_and_removes_the_current_node_call():
    with activity.node_call("R1", "causal_agent", 2):
        assert activity.llm_waiting_for("R1") is None
        with activity.llm_waiting({"model": "m", "schema": "S", "purpose": "answer"}):
            waiting = activity.llm_waiting_for("R1")
            assert waiting["run_id"] == "R1"
            assert waiting["node"] == "causal_agent"
            assert waiting["attempt"] == 2
            assert waiting["model"] == "m"
            assert waiting["started_at"]
        assert activity.llm_waiting_for("R1") is None


def test_llm_waiting_is_removed_when_the_call_raises():
    with activity.node_call("R1", "causal_agent", 1):
        with contextlib.suppress(RuntimeError):
            with activity.llm_waiting({"model": "m"}):
                raise RuntimeError("boom")
        assert activity.llm_waiting_for("R1") is None


def test_llm_waiting_outside_a_node_call_registers_nothing():
    with activity.llm_waiting({"model": "m"}):
        assert activity.llm_waiting_for("R1") is None
    assert activity.llm_waiting_for("R1") is None


def test_an_older_waiting_context_does_not_remove_a_newer_entry():
    with activity.node_call("R1", "causal_agent", 1):
        older = activity.llm_waiting({"model": "old"})
        older.__enter__()
        newer = activity.llm_waiting({"model": "new"})
        newer.__enter__()
        older.__exit__(None, None, None)
        assert activity.llm_waiting_for("R1")["model"] == "new"
        newer.__exit__(None, None, None)
        assert activity.llm_waiting_for("R1") is None


BODY = {"choices": [{"message": {"content": "answer", "tool_calls": []}, "finish_reason": "stop"}]}


def provider():
    return Provider(
        name="test",
        base_url="http://127.0.0.1:1234/v1",
        model="test-model",
        api_key="",
        json_mode="json_schema",
        timeout=1.0,
        max_tokens=None,
        external=False,
        tool_calling=True,
    )


def test_the_llm_client_exposes_the_waiting_call_during_the_http_post():
    observed = {}

    @contextlib.contextmanager
    def opener(request, timeout=None):
        observed["waiting"] = activity.llm_waiting_for("R1")

        class Response:
            def read(self):
                return json.dumps(BODY).encode("utf-8")

        yield Response()

    client = LLMClient(provider=provider(), opener=opener)
    with activity.node_call("R1", "causal_agent", 3):
        turn = client.complete_with_tools([{"role": "user", "content": "hi"}], [], seed=1)
    assert turn.content == "answer"
    assert observed["waiting"]["node"] == "causal_agent"
    assert observed["waiting"]["attempt"] == 3
    assert observed["waiting"]["purpose"] == "tool_turn"
    assert activity.llm_waiting_for("R1") is None
