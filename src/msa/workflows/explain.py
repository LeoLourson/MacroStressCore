"""Explaining a calculated run: the user's question in, an answer from the run's numbers out.

::

  explain ─► [after_explanation] ─► end

``explain`` runs the explanation agent: a bounded LLM ↔ ``mcp-runs`` subgraph
(``msa.agents.explain``). The node is journaled under ``explain/<explanation_id>`` with the
agent's version and a hash of the question, so its LLM and tool calls are audited under
the run, and the same explanation id asked again with another question is refused rather
than answered from the old record. Plugin agents may join ``after_explanation``; they read
the answer and write to their own namespace only. The run itself is never changed.
"""

import operator
from functools import partial
from typing import Annotated, TypedDict

from msa.graph.nodes import explain
from msa.graph.reducers import merge_extensions
from msa.plugin_sdk.agent import AgentPlugin, ExtensionPoint, NodeSpec, StageSpec, WorkflowSpec

WORKFLOW_ID = "explain_results"
VERSION = "1.0.0"


class ExplainInput(TypedDict):
    run_id: str
    explanation_id: str
    question: str
    mode: str


class ExplainRunState(TypedDict, total=False):
    run_id: str
    explanation_id: str
    question: str
    mode: str
    explanation: dict
    status: str
    errors: list[str]
    published: bool
    trace: Annotated[list[str], operator.add]
    extensions: Annotated[dict, merge_extensions]


AGENT = AgentPlugin(
    agent_id="core.explain",
    version="1.0.0",
    label="Объяснение результатов",
    build=lambda ctx: partial(explain.run, context=ctx.services),
    consumes=("run_id", "question"),
    tools=tuple(
        f"runs.{name}"
        for name in (
            "get_run_summary",
            "get_position_metrics",
            "get_metric_provenance",
            "describe_model",
        )
    ),
    core=True,
    description="Отвечает на вопрос по результатам прогона: не более 6 шагов модели и "
    "12 вызовов инструментов, каждое число сверяется с ответами инструментов.",
)

EXPLAIN = WorkflowSpec(
    workflow_id=WORKFLOW_ID,
    version=VERSION,
    label="Объяснение результатов прогона",
    description="Вопрос пользователя → чтение прогона через MCP → ответ с проверенными числами.",
    state_schema=ExplainRunState,
    input_schema=ExplainInput,
    nodes=(
        NodeSpec("explain", "core.explain", "explain", branch="explanation_id"),
        NodeSpec("after_explanation", None, "explain"),
    ),
    edges=(
        ("__start__", "explain"),
        ("explain", "after_explanation"),
        ("after_explanation", "__end__"),
    ),
    extension_points=(
        ExtensionPoint(
            "after_explanation",
            "После объяснения",
            available=("run_id", "question", "explanation"),
        ),
    ),
    stages=(StageSpec("explain", "Объяснение", ("explain", "after_explanation")),),
    core_keys=frozenset(ExplainRunState.__annotations__) - {"trace", "extensions"},
)
