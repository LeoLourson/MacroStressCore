"""The run, node and attempt the current code works for.

The graph runtime sets it around every node; LLM and MCP calls made inside read it, so each
call lands in ``audit_log`` under its run without threading identifiers through agents.
An LLM call waiting for its answer is also visible here, so a screen can show that the model
is working before the answer is recorded.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

_CURRENT: ContextVar[dict | None] = ContextVar("msa_node_call", default=None)
# Run id -> the LLM call of that run waiting for an answer. The API executes runs in its own
# process, so the screens' status requests read the same memory.
_WAITING: dict[str, dict] = {}


def current() -> dict | None:
    return _CURRENT.get()


@contextmanager
def node_call(run_id, node, attempt):
    token = _CURRENT.set({"run_id": run_id, "node": node, "attempt": attempt})
    try:
        yield
    finally:
        _CURRENT.reset(token)


@contextmanager
def llm_waiting(details):
    """Marks the current node's LLM call as waiting for its answer."""
    call = current()
    if call is None:
        yield
        return
    entry = {**call, **details, "started_at": datetime.now(UTC).isoformat()}
    _WAITING[call["run_id"]] = entry
    try:
        yield
    finally:
        if _WAITING.get(call["run_id"]) is entry:
            del _WAITING[call["run_id"]]


def llm_waiting_for(run_id) -> dict | None:
    return _WAITING.get(run_id)
