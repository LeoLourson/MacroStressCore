"""Agents call the read-only MCP servers through the protocol, inside the API process.

Every call is a real MCP round trip over FastMCP's in-memory transport: the arguments are
checked against the tool schema, and the server's ``audited`` wrapper writes the call to
``audit_log`` under the run, node and attempt that made it (``msa.activity``).

All clients run on one event loop in its own thread. FastMCP servers are not safe to share
between event loops: their lifespan and the in-memory task queue (Docket) belong to the loop
that entered first, and a client on another loop can wait for them forever.
"""

import asyncio
import threading
from datetime import date

from fastmcp import Client

from msa import activity

from .registry import build_servers


class ToolError(RuntimeError):
    pass


class ToolGateway:
    def __init__(self, services):
        self.services = services
        self.servers = build_servers(services)
        self._wrapped = {}

    def call(self, server: str, tool: str, **arguments):
        return self.call_as(server, tool, arguments, initiator="workflow")

    def call_as(self, server: str, tool: str, arguments: dict, *, initiator, call_id=None):
        """A call on behalf of the workflow or of an LLM that chose the tool."""
        call = activity.current()
        audit = dict(call) if call else {"node": "standalone", "attempt": 1, "standalone": True}
        audit |= {"initiator": initiator, "call_id": call_id}
        return _sync(self._call("mcp-" + server, tool, {**_json(arguments), "audit": audit}))

    def tools(self, server: str) -> list[dict]:
        """The server's tools as MCP lists them: name, description, input schema."""
        return _sync(self._list("mcp-" + server))

    async def _list(self, name):
        async with Client(self.servers[name]) as client:
            return [
                {
                    "name": item.name,
                    "description": item.description or "",
                    "input_schema": item.inputSchema,
                }
                for item in await client.list_tools()
            ]

    async def _call(self, name, tool, arguments):
        async with Client(self.servers[name]) as client:
            if name not in self._wrapped:
                # FastMCP wraps non-object results as {"result": ...}; its schema says which.
                self._wrapped[name] = {
                    item.name
                    for item in await client.list_tools()
                    if (item.outputSchema or {}).get("x-fastmcp-wrap-result")
                }
            result = await client.call_tool(tool, arguments, raise_on_error=False)
        if result.is_error:
            text = " ".join(getattr(part, "text", "") for part in result.content)
            raise ToolError(f"{name}.{tool}: {text.strip() or 'failed'}")
        data = result.structured_content
        if tool in self._wrapped[name] and isinstance(data, dict):
            data = data.get("result")
        return data


class McpResolver:
    """The snapshot resolution of ``ExposureAgent``, served by ``mcp-portfolio``.

    Bound to the run's portfolio: every call reads that portfolio's positions only.
    """

    def __init__(self, gateway: ToolGateway, portfolio_id: str):
        self.gateway, self.portfolio_id = gateway, portfolio_id

    def resolve(self, context, requirements, *, as_of, snapshot_id):
        answer = self.gateway.call(
            "portfolio",
            "resolve_inputs",
            portfolio_id=self.portfolio_id,
            position_id=context.position_id,
            snapshot_id=snapshot_id,
            as_of=as_of,
            requirements=requirements.model_dump(mode="json"),
        )
        return answer["data"], answer["missing"]


def _json(value):
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


_LOOP = None
_LOCK = threading.Lock()


def _loop():
    global _LOOP
    with _LOCK:
        if _LOOP is None:
            _LOOP = asyncio.new_event_loop()
            threading.Thread(target=_LOOP.run_forever, name="msa-mcp", daemon=True).start()
    return _LOOP


def _sync(coroutine):
    return asyncio.run_coroutine_threadsafe(coroutine, _loop()).result()
