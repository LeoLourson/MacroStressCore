import os

from alembic import context

from msa.db.base import Base
from msa.db.models import TABLES  # noqa: F401
from msa.db.session import engine

config = context.config
url = os.environ.get("MSA_DATABASE_URL", config.get_main_option("sqlalchemy.url"))


def run_migrations_online():
    supplied = config.attributes.get("connection")
    if supplied is not None:
        context.configure(connection=supplied, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    bind = engine(url)
    try:
        with bind.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        bind.dispose()


if context.is_offline_mode():
    raise RuntimeError("Run migrations against an online database")
run_migrations_online()
