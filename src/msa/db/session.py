"""Transactions and data scope. Demo sessions never use the owner's SQL role."""

from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from msa.config import settings


def engine(url=None, **kwargs):
    url = make_url(str(url or settings().database_url))
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    if url.get_backend_name() == "sqlite":
        kwargs.setdefault("connect_args", {"check_same_thread": False, "cached_statements": 0})
        if url.database in (None, "", ":memory:"):
            kwargs.setdefault("poolclass", StaticPool)
    result = create_engine(url, pool_pre_ping=True, **kwargs)
    if url.get_backend_name() == "sqlite":

        @event.listens_for(result, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return result


def authorize_scope(scope, scopes):
    if scope not in {"production", "demo"}:
        raise ValueError("Unknown data scope")
    if scopes is None:  # Trusted internal caller, not an API authentication default.
        return
    required = "demo:" if scope == "demo" else "production:"
    if not any(s == "admin:*" or s.startswith(required) for s in scopes):
        raise PermissionError(f"Credentials do not allow {scope} data")


@contextmanager
def session_scope(bind=None, *, scope="production", scopes=None):
    authorize_scope(scope, scopes)
    owned = bind is None
    bind = bind or engine(settings().demo_database_url if scope == "demo" else None)
    try:
        with bind.connect() as connection:
            raw = None
            if scope == "demo" and bind.dialect.name == "sqlite":
                # SQLite is for local tests only. Deny raw SQL as well as ORM access.
                import sqlite3

                raw = connection.connection.driver_connection

                def authorize(action, arg1, arg2, database, trigger):
                    if action in (
                        sqlite3.SQLITE_READ,
                        sqlite3.SQLITE_INSERT,
                        sqlite3.SQLITE_UPDATE,
                        sqlite3.SQLITE_DELETE,
                    ):
                        return (
                            sqlite3.SQLITE_OK if arg1.startswith("demo_") else sqlite3.SQLITE_DENY
                        )
                    if action in (
                        sqlite3.SQLITE_SELECT,
                        sqlite3.SQLITE_FUNCTION,
                        sqlite3.SQLITE_TRANSACTION,
                        sqlite3.SQLITE_SAVEPOINT,
                        sqlite3.SQLITE_RECURSIVE,
                    ):
                        return sqlite3.SQLITE_OK
                    return sqlite3.SQLITE_DENY

                raw.set_authorizer(authorize)
            try:
                with (
                    Session(
                        connection, expire_on_commit=False, info={"data_scope": scope}
                    ) as session,
                    session.begin(),
                ):
                    if scope == "demo" and bind.dialect.name == "postgresql":
                        session.execute(text("SET LOCAL ROLE msa_demo"))
                        session.execute(text("SET LOCAL search_path = demo, pg_catalog"))
                    yield session
            finally:
                if raw is not None:
                    raw.set_authorizer(None)
    finally:
        if owned:
            bind.dispose()
