"""msa.mcp.audit: CallContext validation and the audited() decorator's digests."""

import asyncio

import pytest
from pydantic import ValidationError

from msa.mcp.audit import CallContext, audited


def test_call_context_requires_run_id_when_not_standalone():
    with pytest.raises(ValidationError, match="Provide run_id"):
        CallContext(node="n", attempt=1, standalone=False, run_id=None)


def test_call_context_requires_no_run_id_when_standalone():
    with pytest.raises(ValidationError, match="Provide run_id"):
        CallContext(node="n", attempt=1, standalone=True, run_id="RUN1")


def test_call_context_accepts_run_id_without_standalone():
    ctx = CallContext(node="n", attempt=1, run_id="RUN1")
    assert ctx.run_id == "RUN1"
    assert ctx.standalone is False


def test_call_context_accepts_standalone_without_run_id():
    ctx = CallContext(node="n", attempt=1, standalone=True)
    assert ctx.run_id is None


def test_call_context_attempt_must_be_at_least_one():
    with pytest.raises(ValidationError):
        CallContext(node="n", attempt=0, standalone=True)


def test_call_context_attempt_is_strict_int_not_bool_or_float():
    with pytest.raises(ValidationError):
        CallContext(node="n", attempt=1.0, standalone=True)


def test_call_context_initiator_defaults_to_workflow():
    ctx = CallContext(node="n", attempt=1, standalone=True)
    assert ctx.initiator == "workflow"


def test_call_context_rejects_unknown_initiator():
    with pytest.raises(ValidationError):
        CallContext(node="n", attempt=1, standalone=True, initiator="human")


def test_call_context_call_id_max_length():
    with pytest.raises(ValidationError):
        CallContext(node="n", attempt=1, standalone=True, call_id="x" * 201)


# -- audited(): digests and the failure path -------------------------------------------------


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


def test_audited_success_records_input_and_output_digests():
    services = FakeServices()

    @audited("my_tool", services)
    def my_tool(x, audit):
        return {"y": x + 1}

    result = asyncio.run(my_tool(1, audit={"run_id": "RUN1", "node": "n", "attempt": 1}))
    assert result == {"y": 2}
    (call,) = services.db.calls
    assert call["action"] == "tool.completed"
    assert call["tool"] == "my_tool"
    assert "input_sha256" in call["details"]
    assert "output_sha256" in call["details"]
    assert "error" not in call["details"]
    assert call["details"]["duration_ms"] >= 0


def test_audited_failure_records_error_and_no_output_digest_and_reraises():
    services = FakeServices()

    @audited("my_tool", services)
    def my_tool(x, audit):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(my_tool(1, audit={"run_id": "RUN1", "node": "n", "attempt": 1}))
    (call,) = services.db.calls
    assert call["action"] == "tool.failed"
    assert "output_sha256" not in call["details"]
    assert call["details"]["error"] == "RuntimeError: boom"


def test_audited_records_initiator_and_call_id_from_the_context():
    services = FakeServices()

    @audited("my_tool", services)
    def my_tool(x, audit):
        return x

    asyncio.run(
        my_tool(
            1,
            audit={
                "run_id": "RUN1",
                "node": "n",
                "attempt": 1,
                "initiator": "llm",
                "call_id": "call-42",
            },
        )
    )
    (call,) = services.db.calls
    assert call["details"]["initiator"] == "llm"
    assert call["details"]["call_id"] == "call-42"


def test_audited_standalone_call_skips_the_run_lookup():
    services = FakeServices()

    @audited("my_tool", services)
    def my_tool(x, audit):
        return x

    asyncio.run(my_tool(1, audit={"standalone": True, "node": "n", "attempt": 1}))
    (call,) = services.db.calls
    assert call["run_id"] is None
    assert call["standalone"] is True
