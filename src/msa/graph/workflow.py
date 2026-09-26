"""The run graph, compiled from the stress-test workflow and the enabled agent plugins;
and the explanation graph of a calculated run."""

from dataclasses import dataclass

from langgraph.checkpoint.memory import InMemorySaver

from msa.db.repositories.runs import MemoryRunRepository
from msa.validators import validate

from .compiler import compile_workflow
from .runtime import NodeContext

WORKFLOW_ID = "stress_test"
EXPLAIN_WORKFLOW_ID = "explain_results"


def build_graph(
    checkpointer,
    *,
    agents,
    repository=None,
    validator=validate,
    auto_approve_demo=False,
    registry=None,
    options=None,
    enabled=(),
    workflow_id=WORKFLOW_ID,
    llm=None,
    gateway=None,
):
    """``enabled`` names agent plugins that are off by default but join this run; ``llm``
    and ``gateway`` are what agent plugins call (their declared tools only)."""
    from msa.platform.registry import registry as current

    if checkpointer is None:
        raise ValueError("Human interrupts require a checkpointer")
    if repository is None and not isinstance(checkpointer, InMemorySaver):
        raise ValueError("A durable checkpointer requires an explicit durable run repository")
    registry = registry or current()
    context = NodeContext(
        agents,
        repository or MemoryRunRepository(),
        validator,
        auto_approve_demo,
        registry=registry,
        options=dict(options or {}),
    )
    spec = registry.workflows[workflow_id]
    return compile_workflow(
        spec,
        registry,
        checkpointer=checkpointer,
        runtime=context,
        enabled=enabled,
        llm=llm,
        gateway=gateway,
    )


@dataclass
class ExplainContext:
    """What the explanation workflow's nodes use: the agent and the run's journal."""

    explainer: object
    repository: object


def build_explanation_graph(
    *, explainer, repository, registry=None, enabled=(), llm=None, gateway=None
):
    """The explanation workflow over one run's journal.

    It has no human stop, so its checkpoints live in memory for one question; the answer,
    the node journal and the audit of its LLM and tool calls are durable.
    """
    from msa.platform.registry import registry as current

    registry = registry or current()
    return compile_workflow(
        registry.workflows[EXPLAIN_WORKFLOW_ID],
        registry,
        checkpointer=InMemorySaver(),
        runtime=ExplainContext(explainer, repository),
        enabled=enabled,
        llm=llm,
        gateway=gateway,
    )
