from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from msa.db.database import Database


@dataclass
class Services:
    db: Database
    scope: str
    actor: str
    storage_root: Path

    def __post_init__(self):
        if self.scope not in {"production", "demo"} or not self.actor.strip():
            raise ValueError("MCP requires an explicit data scope and actor")

    @contextmanager
    def read_session(self):
        with self.db.session(self.scope) as session:
            connection = session.connection()
            raw = None
            if connection.dialect.name == "postgresql":
                session.execute(text("SET TRANSACTION READ ONLY"))
                role = "msa_demo_readonly" if self.scope == "demo" else "msa_readonly"
                session.execute(text(f"SET LOCAL ROLE {role}"))
            else:
                import sqlite3

                raw = connection.connection.driver_connection

                def readonly(action, arg1, arg2, database, trigger):
                    if action == sqlite3.SQLITE_READ:
                        return (
                            sqlite3.SQLITE_OK
                            if self.scope == "production" or arg1.startswith("demo_")
                            else sqlite3.SQLITE_DENY
                        )
                    if action in {
                        sqlite3.SQLITE_SELECT,
                        sqlite3.SQLITE_FUNCTION,
                        sqlite3.SQLITE_TRANSACTION,
                        sqlite3.SQLITE_SAVEPOINT,
                        sqlite3.SQLITE_RECURSIVE,
                    }:
                        return sqlite3.SQLITE_OK
                    return sqlite3.SQLITE_DENY

                raw.set_authorizer(readonly)
            try:
                yield session
            finally:
                if raw is not None:
                    raw.set_authorizer(None)
