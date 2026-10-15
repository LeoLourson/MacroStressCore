from contextlib import contextmanager

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


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
        if mode == "sqlite":
            with SqliteSaver.from_conn_string(connection_string) as saver:
                saver.setup()
                yield saver
        else:
            # A pool, not one connection: the process outlives a database restart, and a
            # connection the server dropped is replaced when the next checkpoint needs one.
            with ConnectionPool(
                connection_string,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                check=ConnectionPool.check_connection,
                open=False,
            ) as pool:
                saver = PostgresSaver(pool)
                saver.setup()
                yield saver
    else:
        raise ValueError(f"Unknown checkpoint mode: {mode}")
