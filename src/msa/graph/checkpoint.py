from contextlib import contextmanager

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver


def thread_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a nonempty string")
    return f"msa:{run_id}"


def run_config(run_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id(run_id)}}


@contextmanager
def build_checkpointer(mode="memory", *, connection_string=None):
    """Keep this context open for the lifetime of the compiled graph."""
    if mode == "memory":
        with InMemorySaver() as saver:
            yield saver
    elif mode in {"sqlite", "postgres"}:
        if not connection_string:
            raise ValueError(f"{mode} requires connection_string")
        saver_type = SqliteSaver if mode == "sqlite" else PostgresSaver
        with saver_type.from_conn_string(connection_string) as saver:
            saver.setup()
            yield saver
    else:
        raise ValueError(f"Unknown checkpoint mode: {mode}")
