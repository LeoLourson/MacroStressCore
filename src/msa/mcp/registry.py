from fastmcp import FastMCP

from .audit import audited

#: Every tool is read-only: business writes belong to the authenticated HTTP platform.
READ_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


def build_servers(services, registry=None):
    """The read-only servers the plugins declare (``Plugin.mcp_servers``), the core's first.

    Each server is ``mcp-<name>``; ``register`` gets the decorator that audits every tool
    and marks it read-only, so no declared tool escapes either.
    """
    from msa.platform.registry import registry as current

    registry = registry or current()
    servers = {}
    for name, spec in registry.mcp_servers.items():
        server = FastMCP("mcp-" + name)

        def tool(fn, server=server, name=name):
            return server.tool(
                audited("mcp-" + name + "." + fn.__name__, services)(fn), annotations=READ_ONLY
            )

        spec.register(tool, services)
        servers["mcp-" + name] = server
    return servers
