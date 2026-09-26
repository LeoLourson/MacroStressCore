"""The run, node and attempt the current code works for.

The graph runtime sets it around every node; LLM and MCP calls made inside read it, so each
call lands in ``audit_log`` under its run without threading identifiers through agents.
"""

from contextlib import contextmanager
from contextvars import ContextVar

_CURRENT: ContextVar[dict | None] = ContextVar("msa_node_call", default=None)


def current() -> dict | None:
    return _CURRENT.get()


@contextmanager
def node_call(run_id, node, attempt):
    token = _CURRENT.set({"run_id": run_id, "node": node, "attempt": attempt})
    try:
        yield
    finally:
        _CURRENT.reset(token)
