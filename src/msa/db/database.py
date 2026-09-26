"""Namespaced sessions and the few generic reads and writes the services share."""

from contextlib import contextmanager
from threading import RLock

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from msa.db.models import tables_for
from msa.db.repositories.common import upsert
from msa.db.session import session_scope


class Database:
    def __init__(self, bind, demo_bind=None):
        self.binds = {"production": bind, "demo": demo_bind or bind}
        self.lock = RLock()

    @contextmanager
    def session(self, scope):
        # SQLite's demo authorizer is connection-local; never share it across transactions.
        bind = self.binds[scope]
        if bind.dialect.name == "sqlite":
            with self.lock, session_scope(bind, scope=scope, scopes={scope + ":*"}) as session:
                yield session
        else:
            with session_scope(bind, scope=scope, scopes={scope + ":*"}) as session:
                yield session

    def get(self, scope, name, key):
        with self.session(scope) as session:
            table = tables_for(session)[name]
            row = session.execute(select(table).filter_by(**key)).mappings().first()
            if row is None:
                raise KeyError(name)
            return dict(row)

    def put(self, scope, name, values):
        with self.session(scope) as session:
            upsert(session, tables_for(session)[name], jsonable_encoder(values))

    def audit(self, scope, actor, action, **kwargs):
        from msa.db.audit import AuditLog

        with self.session(scope) as session:
            return AuditLog(session).log(actor, action, **kwargs)
