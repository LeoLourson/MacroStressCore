from contextlib import ExitStack

import pytest


@pytest.fixture
def graph_factory():
    """A compiled run graph on an in-memory checkpointer and journal."""
    from msa.db.repositories.runs import MemoryRunRepository
    from msa.graph.checkpoint import build_checkpointer
    from msa.graph.workflow import build_graph
    from msa.platform.registry import registry
    from msa.validators import validate

    from .support import agents as default_agents

    with ExitStack() as stack:

        def build(
            *,
            agents=None,
            validator=validate,
            repository=None,
            auto_approve_demo=False,
            enabled=(),
            registry_=None,
        ):
            saver = stack.enter_context(build_checkpointer())
            journal = repository or MemoryRunRepository()
            reg = registry_ or registry()
            graph = build_graph(
                saver,
                agents=agents or default_agents(),
                repository=journal,
                validator=validator,
                auto_approve_demo=auto_approve_demo,
                registry=reg,
                options=reg.run_options("demo"),
                enabled=enabled,
            )
            return graph, journal

        yield build
