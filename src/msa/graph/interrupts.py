from langgraph.types import Command

from .checkpoint import run_config


def pending_interrupt(graph, run_id: str) -> list[dict]:
    snapshot = graph.get_state(run_config(run_id))
    return [
        {"id": item.id, "payload": item.value}
        for task in snapshot.tasks
        for item in task.interrupts
    ]


def start_run(graph, payload: dict):
    config = run_config(payload["run_id"])
    if graph.get_state(config).values:
        raise ValueError("Run already exists; resume it or choose a new run_id")
    return graph.invoke(payload, config=config)


def resume_run(graph, run_id: str, payload):
    pending = pending_interrupt(graph, run_id)
    if not pending:
        raise ValueError("Run has no pending interrupt")
    # An empty dict otherwise means an empty interrupt-ID map to LangGraph.
    return graph.invoke(Command(resume={pending[0]["id"]: payload}), config=run_config(run_id))
