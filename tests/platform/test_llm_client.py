"""msa.integrations.llm.client: ToolTurn/_turn parsing and complete_with_tools, no network."""

import contextlib
import json

import pytest

from msa.integrations.llm.client import LLMClient, ToolCall, ToolCallingUnsupported, ToolTurn
from msa.integrations.llm.providers import Provider, _tool_calling


def provider(*, tool_calling=True, max_tokens=None):
    return Provider(
        name="test",
        base_url="http://127.0.0.1:1234/v1",
        model="test-model",
        api_key="",
        json_mode="json_schema",
        timeout=1.0,
        max_tokens=max_tokens,
        external=False,
        tool_calling=tool_calling,
    )


def client(*, tool_calling=True, opener=None, max_tokens=None, observer=None):
    return LLMClient(
        provider=provider(tool_calling=tool_calling, max_tokens=max_tokens),
        opener=opener,
        observer=observer,
    )


# -- ToolTurn.message() -----------------------------------------------------------------


def test_tool_turn_message_without_calls_has_plain_content():
    turn = ToolTurn(content="hello")
    assert turn.message() == {"role": "assistant", "content": "hello"}


def test_tool_turn_message_with_calls_serialises_arguments_as_json_text():
    turn = ToolTurn(content=None, tool_calls=[ToolCall("c1", "my_tool", {"a": 1})])
    message = turn.message()
    assert message["content"] == ""
    (call,) = message["tool_calls"]
    assert call["id"] == "c1"
    assert call["function"]["name"] == "my_tool"
    assert json.loads(call["function"]["arguments"]) == {"a": 1}


# -- LLMClient._turn(): parsing --------------------------------------------------------------


def test_turn_parses_a_normal_tool_call():
    body = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"id": "call-1", "function": {"name": "get_x", "arguments": '{"a": 1}'}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    turn = client()._turn(body)
    assert turn.tool_calls == [ToolCall("call-1", "get_x", {"a": 1})]
    assert turn.finish_reason == "tool_calls"


def test_turn_missing_call_id_gets_a_positional_fallback_id():
    body = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [{"function": {"name": "get_x", "arguments": "{}"}}],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    turn = client()._turn(body)
    assert turn.tool_calls[0].call_id == "call-0"


def test_turn_raises_on_malformed_json_arguments():
    body = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "get_x", "arguments": "{not json"}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    with pytest.raises(ValueError, match="not JSON"):
        client()._turn(body)


def test_turn_raises_on_empty_answer_with_no_tool_calls():
    body = {"choices": [{"message": {"content": "   "}, "finish_reason": "stop"}]}
    with pytest.raises(ValueError, match="empty"):
        client()._turn(body)


def test_turn_raises_on_finish_reason_length():
    body = {"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]}
    with pytest.raises(ValueError, match="cut at the token limit"):
        client()._turn(body)


def test_turn_raises_when_body_has_no_choices():
    with pytest.raises(ValueError, match="no choices"):
        client()._turn({})


def test_turn_accepts_text_only_answer_with_no_tool_calls():
    body = {"choices": [{"message": {"content": "final answer"}, "finish_reason": "stop"}]}
    turn = client()._turn(body)
    assert turn.content == "final answer"
    assert turn.tool_calls == []


def test_turn_arguments_already_a_dict_is_accepted():
    body = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "get_x", "arguments": {"a": 1}}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }
    turn = client()._turn(body)
    assert turn.tool_calls[0].arguments == {"a": 1}


# -- complete_with_tools(): ToolCallingUnsupported and no-network HTTP mock ------------------


def test_complete_with_tools_raises_when_provider_does_not_support_tools():
    c = client(tool_calling=False)
    with pytest.raises(ToolCallingUnsupported):
        c.complete_with_tools([], [], seed=1)


def _fake_opener(body):
    @contextlib.contextmanager
    def opener(request, timeout=None):
        class Response:
            def read(self_inner):
                return json.dumps(body).encode("utf-8")

        yield Response()

    return opener


def test_complete_with_tools_returns_the_parsed_turn_and_records_usage():
    body = {
        "choices": [{"message": {"content": "answer", "tool_calls": []}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    records = []
    c = client(opener=_fake_opener(body), observer=records.append)
    turn = c.complete_with_tools([{"role": "user", "content": "hi"}], [], seed=1)
    assert turn.content == "answer"
    (record,) = records
    assert record["status"] == "completed"
    assert record["prompt_tokens"] == 10
    assert record["tool_calls"] == []


def test_complete_with_tools_records_a_failed_call_when_parsing_raises():
    body = {"choices": [{"message": {"content": "  "}, "finish_reason": "stop"}]}
    records = []
    c = client(opener=_fake_opener(body), observer=records.append)
    with pytest.raises(ValueError, match="empty"):
        c.complete_with_tools([{"role": "user", "content": "hi"}], [], seed=1)
    (record,) = records
    assert record["status"] == "failed"
    assert "ValueError" in record["error"]


# -- providers._tool_calling(): env override ---------------------------------------------


def test_tool_calling_env_override_true(monkeypatch):
    monkeypatch.setenv("MSA_LLM_TOOL_CALLING", "true")
    assert _tool_calling({"tool_calling": False}) is True


def test_tool_calling_env_override_false(monkeypatch):
    monkeypatch.setenv("MSA_LLM_TOOL_CALLING", "no")
    assert _tool_calling({"tool_calling": True}) is False


def test_tool_calling_without_env_uses_the_profile_default(monkeypatch):
    monkeypatch.delenv("MSA_LLM_TOOL_CALLING", raising=False)
    assert _tool_calling({"tool_calling": True}) is True
    assert _tool_calling({"tool_calling": False}) is False
