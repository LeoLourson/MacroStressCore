"""msa.agents.explain.ExplainAgent: unknown tool names and tool errors fed back to the model.

Uses a scripted fake LLM (complete_with_tools returns queued ToolTurns) and a fake
ToolGateway, so the graph runs with no network and no real MCP server.
"""

from msa.agents.explain import ExplainAgent
from msa.integrations.llm.client import ToolCall, ToolTurn

TOOL_SPECS = [
    {"name": name, "description": "", "input_schema": {"properties": {}, "required": []}}
    for name in (
        "get_run_summary",
        "get_position_metrics",
        "get_metric_provenance",
        "describe_model",
    )
]


class ScriptedLLM:
    tool_calling = True
    model = "fake-model"

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    def complete_with_tools(self, messages, tools, seed):
        self.calls.append({"messages": list(messages), "seed": seed})
        return self.turns.pop(0)


class FakeGateway:
    def __init__(self, *, raises=None, answer=None):
        self.raises = raises
        self.answer = answer if answer is not None else {"ok": True}
        self.calls = []

    def tools(self, server):
        return TOOL_SPECS

    def call_as(self, server, tool, arguments, *, initiator, call_id=None):
        self.calls.append(
            {
                "server": server,
                "tool": tool,
                "arguments": arguments,
                "initiator": initiator,
                "call_id": call_id,
            }
        )
        if self.raises is not None:
            raise self.raises
        return self.answer


def final_turn(text="Готово."):
    return ToolTurn(content=text, tool_calls=[])


# -- unknown tool name --------------------------------------------------------------------


def test_unknown_tool_name_is_reported_back_to_the_model_and_run_still_completes():
    first = ToolTurn(
        content=None,
        tool_calls=[ToolCall("c1", "not_a_real_tool", {})],
    )
    llm = ScriptedLLM([first, final_turn()])
    gateway = FakeGateway()
    agent = ExplainAgent(llm=llm, tools=gateway)

    explanation = agent.run({"run_id": "R1", "question": "Что произошло?"})

    assert explanation.mode == "llm"
    assert explanation.text == "Готово."
    (call,) = explanation.tool_calls
    assert call.name == "not_a_real_tool"
    assert call.ok is False
    assert "неизвестный инструмент" in call.error
    # The gateway itself is never called for an unknown tool.
    assert gateway.calls == []
    # The second model turn saw the tool's error as a tool message.
    second_messages = llm.calls[1]["messages"]
    tool_message = next(m for m in second_messages if m.get("role") == "tool")
    assert "неизвестный инструмент" in tool_message["content"]


# -- a real tool call that raises is fed back as an error, not raised to the caller --------


def test_tool_call_error_is_fed_back_to_the_model_as_a_tool_message():
    first = ToolTurn(
        content=None,
        tool_calls=[ToolCall("c1", "get_run_summary", {})],
    )
    llm = ScriptedLLM([first, final_turn()])
    gateway = FakeGateway(raises=ValueError("run not found"))
    agent = ExplainAgent(llm=llm, tools=gateway)

    explanation = agent.run({"run_id": "R1", "question": "Что произошло?"})

    assert explanation.mode == "llm"
    (call,) = explanation.tool_calls
    assert call.name == "get_run_summary"
    assert call.ok is False
    assert "run not found" in call.error
    # The gateway call itself was attempted with the LLM as initiator.
    (attempted,) = gateway.calls
    assert attempted["initiator"] == "llm"
    assert attempted["tool"] == "get_run_summary"
    second_messages = llm.calls[1]["messages"]
    tool_message = next(m for m in second_messages if m.get("role") == "tool")
    assert "run not found" in tool_message["content"]


def test_a_successful_tool_call_is_marked_ok_with_no_error():
    first = ToolTurn(content=None, tool_calls=[ToolCall("c1", "get_run_summary", {})])
    llm = ScriptedLLM([first, final_turn()])
    gateway = FakeGateway(answer={"counts": {"positions": 1}})
    agent = ExplainAgent(llm=llm, tools=gateway)

    explanation = agent.run({"run_id": "R1", "question": "Что произошло?"})

    (call,) = explanation.tool_calls
    assert call.ok is True
    assert call.error is None


def test_run_id_is_injected_into_tool_arguments_and_stripped_from_what_is_recorded():
    first = ToolTurn(
        content=None,
        tool_calls=[ToolCall("c1", "get_position_metrics", {"position_id": "POS1"})],
    )
    llm = ScriptedLLM([first, final_turn()])
    gateway = FakeGateway(answer={"position_id": "POS1"})
    agent = ExplainAgent(llm=llm, tools=gateway)

    explanation = agent.run({"run_id": "R1", "question": "Что с POS1?"})

    (attempted,) = gateway.calls
    assert attempted["arguments"]["run_id"] == "R1"
    (call,) = explanation.tool_calls
    # The recorded call's own arguments do not repeat run_id (the agent adds it, not the model).
    assert "run_id" not in call.arguments
