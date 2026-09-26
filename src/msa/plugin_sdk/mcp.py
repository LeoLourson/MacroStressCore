"""A plugin's MCP server: read-only tools its agents call through the platform's gateway.

A plugin declares its servers in ``Plugin.mcp_servers``. ``register(tool, services)`` defines
the tools with the ``tool`` decorator the platform passes in, as the core servers do
(``mcp-models``, ``mcp-portfolio``, ``mcp-runs``): the decorator wraps every function in the
audit — each call lands in ``audit_log`` with its run, node, attempt, initiator and the
digests of its arguments and answer — and marks it read-only. There is no other way to add
a tool, so neither the audit nor the read-only marking can be skipped.

- The server's name starts with ``<plugin_id>.``; the gateway and the audit call it
  ``mcp-<name>``. An agent declares a tool as ``<name>.<tool>`` in ``AgentPlugin.tools``.
- A tool takes ``audit: CallContext`` as its last parameter (the gateway fills it; the
  registry refuses a tool without it) and returns JSON: a dict, a list or a scalar.
- ``register`` must not use ``services`` while it defines the tools, only inside them: the
  registry lists a server's tools by calling ``register`` without services.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from msa.mcp.audit import CallContext


class McpServices(Protocol):
    """What the platform hands to ``register``: the calling contour and a read-only session."""

    #: ``production`` or ``demo``: the data scope every call of this gateway reads.
    scope: str
    #: Who the calls are made as (``agent:msa``).
    actor: str

    def read_session(self) -> AbstractContextManager[Any]:
        """A database session of the scope in read-only mode."""
        ...


@dataclass(frozen=True)
class McpServerSpec:
    name: str
    #: ``fn(tool, services)``: defines the server's tools with ``@tool``.
    register: Callable[[Callable, McpServices], None]
    label: str = ""
    description: str = ""


__all__ = ["CallContext", "McpServerSpec", "McpServices"]
