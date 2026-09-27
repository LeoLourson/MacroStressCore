from langgraph.types import Command

from .checkpoint import run_config


def pending_interrupt(graph, run_id: str) -> list[dict]:
    snapshot = graph.get_state(run_config(run_id))
    return [
        {"id": item.id, "payload": item.value}
        for task in snapshot.tasks
        for item in task.interrupts
    ]


def drive(graph, payload, config, on_step=None):
    """``graph.invoke`` that hands every step to ``on_step(state, upcoming)``.

    ``upcoming`` names the nodes the graph starts next: only the graph knows which way a
    route turns. The result is what ``invoke`` returns: the last state, with
    ``__interrupt__`` when the run stopped for a person.
    """
    latest, interrupts = None, []
    modes = ["updates", "values", "checkpoints"]
    for mode, chunk in graph.stream(payload, config=config, stream_mode=modes):
        if mode == "updates" and isinstance(chunk, dict) and "__interrupt__" in chunk:
            interrupts.extend(chunk["__interrupt__"])
        elif mode == "values":
            latest = chunk
        # The first checkpoint of a new run holds the input before any node has read it.
        elif mode == "checkpoints" and on_step is not None and chunk["next"] != ["__start__"]:
            on_step(chunk["values"], chunk["next"])
    if interrupts:
        return (
            {**latest, "__interrupt__": interrupts}
            if isinstance(latest, dict)
            else {"__interrupt__": interrupts}
        )
    return latest


def start_run(graph, payload: dict, on_step=None):
    config = run_config(payload["run_id"])
    if graph.get_state(config).values:
        raise ValueError("Run already exists; resume it or choose a new run_id")
    return drive(graph, payload, config, on_step)


def resume_run(graph, run_id: str, payload, on_step=None):
    pending = pending_interrupt(graph, run_id)
    if not pending:
        raise ValueError("Run has no pending interrupt")
    # An empty dict otherwise means an empty interrupt-ID map to LangGraph.
    return drive(graph, Command(resume={pending[0]["id"]: payload}), run_config(run_id), on_step)
