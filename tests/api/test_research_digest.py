"""The API end to end with the ``research.digest`` agent plugin enabled: it calls its own
read-only MCP tool (``research.notes.slice_digest``) through the run's real gateway, and the
call is audited like any other MCP tool call of the run.
"""

import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from demo.seed_demo import seed_demo
from msa.api.main import create_app
from msa.db.migrate import migrate
from msa.db.session import engine
from msa.graph.checkpoint import build_checkpointer

ANALYST, RISK = "analyst-key", "risk-key"
FINAL = {"human_fix_graph", "human_approval", "completed", "rejected", "failed"}
RESEARCH_AGENTS = ["research.concentration", "research.brief", "research.digest"]


def keys():
    expires = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    return {
        ANALYST: {
            "actor": "analyst",
            "role": "analyst",
            "scopes": ["demo:*", "production:*"],
            "expires_at": expires,
        },
        RISK: {
            "actor": "risk",
            "role": "risk_manager",
            "scopes": ["demo:*", "production:*"],
            "expires_at": expires,
        },
    }


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("research-digest-api")
    bind = engine(f"sqlite:///{root / 'msa.db'}")
    migrate(bind)
    seed_demo(bind)
    with build_checkpointer() as saver:
        app = create_app(
            bind=bind,
            keys=keys(),
            checkpointer=saver,
            storage_root=root / "objects",
            mock_llm=True,
            recover=False,
        )
        with TestClient(app) as test_client:
            yield test_client
    bind.dispose()


def get(client, path, key=ANALYST, **params):
    response = client.get(path, headers={"X-API-Key": key}, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def post(client, path, body, key=ANALYST, expect=(200, 201, 202)):
    response = client.post(path, headers={"X-API-Key": key}, json=body)
    assert response.status_code in expect, response.text
    return response.json()


def wait(client, run_id):
    for _ in range(600):
        status = get(client, f"/v1/demo/runs/{run_id}")
        if status["status"] in FINAL:
            return status
        time.sleep(0.05)
    raise AssertionError("run did not stop")


def test_research_digest_calls_its_own_mcp_tool_and_the_call_is_audited(client):
    status = post(
        client,
        "/v1/demo/runs",
        {
            "portfolio_id": "DEMO-1",
            "event": {"kind": "library", "id": "EVENT-A"},
            "agents": RESEARCH_AGENTS,
        },
    )
    status = wait(client, status["run_id"])
    run_id = status["run_id"]
    assert status["status"] == "human_fix_graph", status
    stop = status["pending_interrupt"][0]["payload"]
    post(client, f"/v1/demo/runs/{run_id}/resume", {"graph": stop["graph"]})
    status = wait(client, run_id)
    assert status["status"] == "human_approval", status

    artifacts = get(client, f"/v1/demo/runs/{run_id}/artifacts")
    digest = artifacts["extensions"]["research.digest"]["digest"]
    slice_ids = set(artifacts["portfolio"]["slices"])
    assert {row["slice_id"] for row in digest} == slice_ids
    for row in digest:
        assert row["positions"] >= 0
        assert 0 <= row["top_share"] <= 1
        assert 0 <= row["herfindahl"] <= 1

    activity = get(client, f"/v1/demo/runs/{run_id}/activity")
    tool = "mcp-research.notes.slice_digest"
    calls = [item for item in activity["items"] if item["name"] == tool]
    assert calls, "the digest tool was never called"
    for item in calls:
        assert item["node"] == "research.digest"
        assert item["initiator"] == "workflow"
        assert item["status"] == "completed"

    post(client, f"/v1/demo/runs/{run_id}/resume", {"approved": True}, key=RISK)
    assert wait(client, run_id)["status"] == "completed"
