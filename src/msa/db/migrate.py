"""Programmatic Alembic entry point, also used by integration tests."""

from pathlib import Path

from alembic import command
from alembic.config import Config


def migrate(bind, revision="head", *, downgrade=False):
    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "migrations/alembic.ini"))
    with bind.begin() as connection:
        config.attributes["connection"] = connection
        (command.downgrade if downgrade else command.upgrade)(config, revision)
