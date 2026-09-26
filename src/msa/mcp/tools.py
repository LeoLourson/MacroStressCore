"""What an agent sees of the MCP gateway: only the tools it declared in ``AgentPlugin.tools``.

Kept apart from the gateway itself so that compiling a workflow does not load the MCP
client.
"""


class ToolError(RuntimeError):
    """A tool call failed; the message names the tool."""


class ToolNotDeclared(PermissionError):
    """An agent called a tool it did not declare in ``AgentPlugin.tools``."""


class DeclaredTools:
    """An agent's view of the gateway: only the tools it declared, audited like any call.

    ``gateway`` is ``None`` outside a run with MCP servers (a graph built for a test): a call
    then fails with that reason instead of reaching a server.
    """

    def __init__(self, gateway, agent_id: str, declared):
        self.gateway, self.agent_id = gateway, agent_id
        self.declared = tuple(declared)
        #: Function names an LLM sees (dots are not allowed there) -> ``server.tool``.
        self._functions = {tool.replace(".", "__"): tool for tool in self.declared}

    def call(self, tool: str, /, **arguments):
        return self.call_as(tool, arguments, initiator="workflow")

    def call_as(self, tool: str, arguments: dict, *, initiator="llm", call_id=None):
        tool = self._functions.get(tool, tool)
        if tool not in self.declared:
            raise ToolNotDeclared(
                f"{self.agent_id} did not declare tool {tool!r}; "
                f"declared: {', '.join(self.declared) or 'none'}"
            )
        if self.gateway is None:
            raise ToolError(f"{tool}: no MCP gateway in this run")
        server, _, name = tool.rpartition(".")
        return self.gateway.call_as(server, name, arguments, initiator=initiator, call_id=call_id)

    def functions(self) -> list[dict]:
        """The declared tools as OpenAI function definitions, without the audit argument."""
        if self.gateway is None:
            return []
        specs = []
        for function, tool in self._functions.items():
            server, _, name = tool.rpartition(".")
            item = next(t for t in self.gateway.tools(server) if t["name"] == name)
            schema = dict(item["input_schema"] or {})
            properties = {k: v for k, v in (schema.get("properties") or {}).items() if k != "audit"}
            required = [k for k in schema.get("required", []) if k in properties]
            specs.append(
                {
                    "type": "function",
                    "function": {
                        "name": function,
                        "description": item["description"],
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
                    },
                }
            )
        return specs
