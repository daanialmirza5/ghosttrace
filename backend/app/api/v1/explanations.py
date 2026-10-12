"""Explanation and settings endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app import __version__
from app.api.deps import DatabaseDep, SettingsDep
from app.models.base import utcnow
from app.repositories import incidents as incident_repo
from app.services.explanations import explain_incident
from app.services.incidents import referenced_event_ids, window_events

router = APIRouter(tags=["explanations"])


class StepOut(BaseModel):
    step: str
    evidence_event_ids: list[str]


class ExplanationOut(BaseModel):
    incident_id: str
    generated_at: datetime
    source: Literal["ai", "deterministic"]
    provider: str | None
    model: str | None
    label: str
    disclosure: str
    raw_event_messages_sent: bool
    fallback_reason: str | None
    summary: str
    investigation_steps: list[StepOut]
    cited_event_ids: list[str]


@router.post("/incidents/{incident_id}/explanations", response_model=ExplanationOut)
async def create_explanation(
    incident_id: str, database: DatabaseDep, settings: SettingsDep
) -> ExplanationOut:
    """Summarise the incident's evidence.

    Uses the configured AI provider when enabled; otherwise (or on any provider failure)
    returns the deterministic template and says why in ``fallback_reason``.
    """

    def work() -> ExplanationOut:
        with database.session_factory() as session:
            record = incident_repo.get_incident(session, incident_id)
            messages: dict[str, str] = {}
            if settings.ai_enabled and settings.ai_send_event_messages:
                wanted = referenced_event_ids(record)
                messages = {
                    e.event_id: e.message[:500]
                    for e in window_events(session, record)
                    if e.event_id in wanted
                }
            result = explain_incident(record, settings, messages=messages)
            return ExplanationOut(incident_id=record.id, generated_at=utcnow(), **result)

    return await run_in_threadpool(work)


class SettingsOut(BaseModel):
    version: str
    environment: str
    database_backend: str
    max_upload_bytes: int
    max_records_per_import: int
    retention_hours: int
    rate_limit_per_minute: int
    cors_origins: list[str]
    ai_provider: str
    ai_enabled: bool
    ai_model: str | None
    ai_send_event_messages: bool


@router.get("/settings", response_model=SettingsOut)
def get_settings_view(settings: SettingsDep) -> SettingsOut:
    """Effective non-secret configuration (secrets are never returned)."""
    return SettingsOut(
        version=__version__,
        environment=settings.environment,
        database_backend="sqlite" if settings.is_sqlite else settings.database_url.split(":")[0],
        max_upload_bytes=settings.max_upload_bytes,
        max_records_per_import=settings.max_records_per_import,
        retention_hours=settings.retention_hours,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        cors_origins=settings.cors_origins,
        ai_provider=settings.ai_provider,
        ai_enabled=settings.ai_enabled,
        ai_model=settings.ai_model if settings.ai_enabled else None,
        ai_send_event_messages=settings.ai_send_event_messages,
    )
