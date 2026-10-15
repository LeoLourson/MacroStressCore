"""Explaining a calculated run through the API.

- a run without results cannot be explained;
- a provider that does not call tools gets the structured answer from the run summary;
- a tool-calling model reads the run through ``mcp-runs``: its calls are audited as the
  LLM's, under the explanation's node, and every number of its answer is found in them;
- an invented number gets one repair turn, then the structured answer;
- the model is stopped after 6 turns and 12 tool calls;
- the tools read only the run the explanation belongs to;
- the same explanation id asked again with another question is refused, not replayed.
"""

import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from demo.seed_demo import seed_demo
from msa.graph import activity
from msa.agents.explain import MAX_ROUNDS, MAX_TOOL_CALLS, verify
from msa.api.main import create_app
from msa.db.migrate import migrate
from msa.db.repositories.runs import MemoryRunRepository
from msa.db.session import engine
from msa.graph.checkpoint import build_checkpointer, run_config
from msa.graph.runtime import InputsChanged
from msa.graph.workflow import build_explanation_graph
from msa.integrations.llm.client import ToolCall, ToolTurn
from msa.mcp.gateway import ToolError

ANALYST = "analyst-key"
FINAL = {"human_fix_graph", "human_approval", "completed", "rejected", "failed"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("explain")
    bind = engine(f"sqlite:///{root / 'msa.db'}")
    migrate(bind)
    seed_demo(bind)
    expires = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    keys = {
        ANALYST: {
            "actor": "analyst",
            "role": "analyst",
            "scopes": ["demo:*"],
            "expires_at": expires,
        }
    }
    with build_checkpointer() as saver:
        app = create_app(
            bind=bind,
            keys=keys,
            checkpointer=saver,
            storage_root=root / "objects",
            mock_llm=True,
            recover=False,
        )
        with TestClient(app) as test_client:
            yield test_client
    bind.dispose()


def get(client, path):
    response = client.get(path, headers={"X-API-Key": ANALYST})
    assert response.status_code == 200, response.text
    return response.json()


def post(client, path, body, expect=(200, 202)):
    response = client.post(path, headers={"X-API-Key": ANALYST}, json=body)
    assert response.status_code in expect, response.text
    return response.json()


def wait_run(client, run_id):
    for _ in range(600):
        status = get(client, f"/v1/demo/runs/{run_id}")
        if status["status"] in FINAL:
            return status
        time.sleep(0.05)
    raise AssertionError("run did not stop")


def ask(client, run_id, question):
    record = post(client, f"/v1/demo/runs/{run_id}/explanations", {"question": question})
    for _ in range(600):
        found = get(client, f"/v1/demo/runs/{run_id}/explanations/{record['explanation_id']}")
        if found["status"] in {"completed", "failed"}:
            return found
        time.sleep(0.05)
    raise AssertionError("explanation did not finish")


@pytest.fixture(scope="module")
def run_id(client):
    status = post(
        client,
        "/v1/demo/runs",
        {"portfolio_id": "MULTI-ASSET", "event": {"kind": "library", "id": "RECYCLING-FEE"}},
    )
    status = wait_run(client, status["run_id"])
    assert status["status"] == "human_fix_graph"
    # Before the scenario is confirmed there is nothing calculated to explain.
    post(
        client,
        f"/v1/demo/runs/{status['run_id']}/explanations",
        {"question": "Почему?"},
        expect=(409,),
    )
    stop = status["pending_interrupt"][0]["payload"]
    post(client, f"/v1/demo/runs/{status['run_id']}/resume", {"graph": stop["graph"]})
    assert wait_run(client, status["run_id"])["status"] == "human_approval"
    return status["run_id"]


class ScriptedLLM:
    """A tool-calling model that follows a script: ``script(turn, messages) -> ToolTurn``."""

    tool_calling = True
    model = "scripted"

    def __init__(self, script):
        self.script, self.turns, self.tools = script, 0, None

    def complete_with_tools(self, messages, tools, seed):
        self.tools = tools
        turn = self.script(self.turns, messages)
        self.turns += 1
        return turn


def use(client, llm):
    client.app.state.agents.explain_llm = lambda scope: llm


@pytest.fixture(autouse=True)
def mock_model(client):
    yield
    client.app.state.agents.__dict__.pop("explain_llm", None)


def tool_answer(messages, name_index=-1):
    return json.loads([m for m in messages if m["role"] == "tool"][name_index]["content"])


def ru(value):
    return f"{value:.2f}".replace(".", ",")


def test_without_tool_calling_the_answer_is_the_run_summary(client, run_id):
    found = ask(client, run_id, "Почему выросли потери?")
    answer = found["answer"]
    assert found["status"] == "completed"
    assert answer["mode"] == "structured"
    assert answer["fallback_reason"] == "tool_calling_unsupported"
    assert [s["title"] for s in answer["sections"]][:2] == ["Прогон", "Срезы портфеля"]
    assert "P5 / P50 / P95" in answer["text"]
    calls = [
        i
        for i in get(client, f"/v1/demo/runs/{run_id}/activity")["items"]
        if i["node"] == f"explain/{found['explanation_id']}"
    ]
    assert [(c["name"], c["initiator"]) for c in calls] == [
        ("mcp-runs.get_run_summary", "workflow")
    ]
    listed = get(client, f"/v1/demo/runs/{run_id}/explanations")
    assert found["explanation_id"] in {item["explanation_id"] for item in listed}


def test_a_tool_calling_model_answers_with_verified_numbers(client, run_id):
    def script(turn, messages):
        if turn == 0:
            return ToolTurn(None, [ToolCall("c1", "get_run_summary", {"run_id": "other"})])
        if turn == 1:
            summary = tool_answer(messages)
            position = next(p for p in summary["positions"] if p["execution"] == "completed")
            return ToolTurn(
                None,
                [ToolCall("c2", "get_position_metrics", {"position_id": position["position_id"]})],
            )
        summary = tool_answer(messages, 0)
        credit = next(s for s in summary["slices"] if s["slice_id"] == "credit.loss")
        text = (
            f"Кредитные потери портфеля: P5 / P50 / P95 = {ru(credit['p05'])} / "
            f"{ru(credit['p50'])} / {ru(credit['p95'])} млн руб. [{credit['path_p50']}]; "
            f"покрытие {credit['covered_percent']:.0f} %."
        )
        return ToolTurn(text, [])

    llm = ScriptedLLM(script)
    use(client, llm)
    found = ask(client, run_id, "Какие потери по кредитному срезу?")
    answer = found["answer"]
    assert answer["mode"] == "llm", answer
    assert answer["rounds"] == 3 and answer["unverified"] == []
    assert {n["tool"] for n in answer["numbers"]} == {"get_run_summary"}
    # The model never sees run_id: the agent adds its own run to every call.
    names = {t["function"]["name"] for t in llm.tools}
    assert names == {
        "get_run_summary",
        "get_position_metrics",
        "get_metric_provenance",
        "describe_model",
    }
    assert all("run_id" not in t["function"]["parameters"]["properties"] for t in llm.tools)
    assert [c["arguments"] for c in answer["tool_calls"]][0] == {}
    items = [
        i
        for i in get(client, f"/v1/demo/runs/{run_id}/activity")["items"]
        if i["node"] == f"explain/{found['explanation_id']}"
    ]
    assert [(i["name"], i["initiator"], i["details"]["call_id"]) for i in items] == [
        ("mcp-runs.get_run_summary", "llm", "c1"),
        ("mcp-runs.get_position_metrics", "llm", "c2"),
    ]
    assert all(len(i["details"]["input_sha256"]) == 64 for i in items)


def test_an_invented_number_gets_one_repair_then_the_summary(client, run_id):
    def script(turn, messages):
        if turn == 0:
            return ToolTurn(None, [ToolCall("c1", "get_run_summary", {})])
        return ToolTurn("Потери составят 123456,78 млн руб.", [])

    llm = ScriptedLLM(script)
    use(client, llm)
    answer = ask(client, run_id, "Сколько потеряем?")["answer"]
    assert llm.turns == 3  # the tool turn, the answer and the one repair
    assert answer["mode"] == "structured"
    assert answer["fallback_reason"] == "unverified_numbers"
    assert answer["unverified"] == ["123456.78"]


def test_the_model_is_stopped_after_its_limits(client, run_id):
    def script(turn, messages):
        return ToolTurn(None, [ToolCall(f"c{turn}-{i}", "get_run_summary", {}) for i in range(3)])

    llm = ScriptedLLM(script)
    use(client, llm)
    answer = ask(client, run_id, "Расскажи всё")["answer"]
    assert llm.turns == MAX_ROUNDS
    assert answer["fallback_reason"] == "round_limit"
    executed = [c for c in answer["tool_calls"] if c["ok"]]
    assert len(executed) == MAX_TOOL_CALLS
    assert all(c["error"] for c in answer["tool_calls"] if not c["ok"])


def test_the_tools_read_only_the_run_of_the_call(client, run_id):
    gateway = client.app.state.agents.tools("demo")
    with activity.node_call(run_id, "explain/test", 1), pytest.raises(ToolError, match="bound"):
        gateway.call_as("runs", "get_run_summary", {"run_id": "another-run"}, initiator="llm")


def test_a_repeated_explanation_with_another_question_is_refused():
    class Explainer:
        def run(self, payload):
            from msa.contracts.explanation import Explanation

            return Explanation(
                run_id=payload["run_id"],
                question=payload["question"],
                mode="structured",
                text="—",
                prompt_version="v1",
            )

    repository = MemoryRunRepository()
    graph = build_explanation_graph(explainer=Explainer(), repository=repository)
    first = {"run_id": "R", "explanation_id": "E", "question": "Почему?", "mode": "demo"}
    assert graph.invoke(first, config=run_config("R"))["explanation"]["question"] == "Почему?"
    again = build_explanation_graph(explainer=Explainer(), repository=repository)
    assert again.invoke(first, config=run_config("R"))["explanation"]["question"] == "Почему?"
    with pytest.raises(InputsChanged):
        again.invoke({**first, "question": "Зачем?"}, config=run_config("R"))


def test_numbers_are_found_as_given_rounded_or_in_percent():
    sources = [{"tool": "t", "values": ["0.1534", "1234.5678", "-12.3"]}]
    checked, unverified = verify(
        "Доля 15,3 %, сумма 1 234,57 млн, убыток 12,3; ставка 7,77. [/positions/A1/metrics/x/p50]",
        sources,
    )
    assert [c["text"] for c in checked] == ["15.3", "1234.57", "12.3"]
    assert checked[0]["scaled"] is True
    assert unverified == ["7.77"]
