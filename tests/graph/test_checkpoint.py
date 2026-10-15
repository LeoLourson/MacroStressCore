"""The Postgres checkpointer outlives its connections: a database restart must not fail runs."""

import os

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from msa.graph.checkpoint import build_checkpointer, run_config

URL = os.getenv("MSA_TEST_POSTGRES_URL")


@pytest.mark.skipif(not URL, reason="needs a PostgreSQL server: set MSA_TEST_POSTGRES_URL")
def test_postgres_checkpointer_survives_dropped_connections():
    name = "msa-checkpoint-test"
    with build_checkpointer(
        "postgres", connection_string=make_conninfo(URL, application_name=name)
    ) as saver:
        assert saver.get_tuple(run_config("no-such-run")) is None
        # What a server restart does to the checkpointer's connections, and only to them.
        with psycopg.connect(URL, autocommit=True) as admin:
            admin.execute(
                "select pg_terminate_backend(pid) from pg_stat_activity"
                " where application_name = %s",
                (name,),
            )
        assert saver.get_tuple(run_config("no-such-run")) is None
