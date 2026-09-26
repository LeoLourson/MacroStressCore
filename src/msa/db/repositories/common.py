"""Dialect-aware atomic upserts; repositories never commit callers' transactions."""

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


def upsert(session, table, values, *, update_columns=None):
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = insert(table).values(**values)
    keys = [column.name for column in table.primary_key]
    columns = update_columns or [name for name in values if name not in keys]
    statement = statement.on_conflict_do_update(
        index_elements=keys, set_={name: getattr(statement.excluded, name) for name in columns}
    )
    session.execute(statement)


def insert_once(session, table, values) -> bool:
    """Insert a row unless its key exists; True when this call inserted it."""
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    return session.execute(insert(table).values(**values).on_conflict_do_nothing()).rowcount == 1


def require_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")
    return value
