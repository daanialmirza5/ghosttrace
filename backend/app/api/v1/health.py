"""Liveness and readiness probes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app import __version__
from app.api.deps import DatabaseDep, SettingsDep
from app.core.migrations import current_revisions, head_revisions

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class ReadinessCheck(BaseModel):
    name: str
    ok: bool
    detail: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: list[ReadinessCheck]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness: the process is running and can serve requests."""
    return HealthResponse(status="ok", version=__version__)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def ready(request: Request, database: DatabaseDep, settings: SettingsDep) -> JSONResponse:
    """Readiness: startup succeeded, the database answers, and its schema is at head."""
    checks: list[ReadinessCheck] = []

    startup_error: str | None = getattr(request.app.state, "startup_error", None)
    checks.append(
        ReadinessCheck(
            name="startup",
            ok=startup_error is None,
            detail=startup_error or "initialisation completed",
        )
    )

    try:
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks.append(ReadinessCheck(name="database", ok=True, detail="connected"))
        current = current_revisions(database.engine)
        heads = head_revisions(settings.database_url)
        at_head = current == heads
        checks.append(
            ReadinessCheck(
                name="schema",
                ok=at_head,
                detail="at head" if at_head else "migrations pending",
            )
        )
    except Exception:  # pragma: no cover - exercised via an unreachable database in tests
        checks.append(ReadinessCheck(name="database", ok=False, detail="unreachable"))

    ok = all(check.ok for check in checks)
    body = ReadinessResponse(status="ready" if ok else "not_ready", checks=checks)
    return JSONResponse(status_code=200 if ok else 503, content=body.model_dump())
