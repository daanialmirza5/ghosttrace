"""FastAPI dependencies shared by route modules."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import Database


def get_database(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session(database: Annotated[Database, Depends(get_database)]) -> Iterator[Session]:
    yield from database.session()


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
DatabaseDep = Annotated[Database, Depends(get_database)]
