from copy import deepcopy

from pydantic import BaseModel, TypeAdapter


class MockLLM:
    """A deterministic, schema-checked response fixture; no GPU or network needed."""

    #: Fixtures do not choose tools; an explanation falls back to its structured form.
    tool_calling = False

    def __init__(self, response):
        self.response = deepcopy(response)

    def complete(self, messages: list[dict], schema: type[BaseModel], seed: int):
        return TypeAdapter(schema).validate_python(deepcopy(self.response))
