"""The answer to a question about a calculated run.

An explanation is either written by an LLM from what the run's MCP tools returned, with
every number in it found in those answers, or assembled from the run's summary without a
model (``structured``), with the reason the model's answer was not used.
"""

from typing import Literal

from pydantic import Field

from .common import Contract


class ToolUse(Contract):
    call_id: str
    name: str
    arguments: dict
    ok: bool
    error: str | None = None


class CheckedNumber(Contract):
    """A number of the answer and the tool answer it was found in."""

    text: str
    tool: str
    #: The number as the tool gave it; ``scaled`` when the answer shows it in percent.
    source_value: float
    scaled: bool = False


class ExplanationSection(Contract):
    title: str
    lines: list[str] = Field(default_factory=list)


class Explanation(Contract):
    run_id: str
    question: str
    mode: Literal["llm", "structured"]
    text: str
    sections: list[ExplanationSection] = Field(default_factory=list)
    numbers: list[CheckedNumber] = Field(default_factory=list)
    #: Numbers of the LLM's last answer that no tool answer contained (structured mode).
    unverified: list[str] = Field(default_factory=list)
    tool_calls: list[ToolUse] = Field(default_factory=list)
    rounds: int = 0
    fallback_reason: str | None = None
    model: str | None = None
    prompt_version: str
