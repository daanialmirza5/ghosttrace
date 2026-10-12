"""Programmatic Alembic helpers used at startup and by the readiness probe."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

from app.core.config import BACKEND_DIR


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    # ConfigParser interpolation treats "%" specially (URL-encoded passwords).
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    return config


def upgrade_to_head(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")


def head_revisions(database_url: str) -> set[str]:
    script = ScriptDirectory.from_config(alembic_config(database_url))
    return set(script.get_heads())


def current_revisions(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        return set(context.get_current_heads())
