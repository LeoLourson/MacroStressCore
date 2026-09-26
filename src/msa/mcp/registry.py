from fastmcp import FastMCP

from . import models, portfolio, runs
from .audit import audited


def build_servers(services):
    """The read-only servers: portfolio data, the calculation models and a run's results."""
    servers = {}
    for name, module in (("models", models), ("portfolio", portfolio), ("runs", runs)):
        server = FastMCP("mcp-" + name)

        def tool(fn, server=server, name=name):
            return server.tool(
                audited("mcp-" + name + "." + fn.__name__, services)(fn),
                annotations={
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            )

        module.register(tool, services)
        servers["mcp-" + name] = server
    return servers
