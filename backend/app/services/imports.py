"""Import orchestration: validate an upload, persist it, and (later) analyse it."""

from __future__ import annotations

import hashlib
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.base import utcnow
from app.models.imports import ImportRecord
from app.repositories import imports as import_repo
from app.services.ingestion import IngestionLimits, ingest_bytes
from app.services.ingestion.parsers import Format


def limits_from(settings: Settings) -> IngestionLimits:
    return IngestionLimits(
        max_records=settings.max_records_per_import,
        max_line_bytes=settings.max_line_bytes,
        max_reported_errors=settings.max_reported_errors,
        max_attributes=settings.max_attributes_per_event,
    )


def import_content(
    session: Session,
    settings: Settings,
    *,
    content: bytes,
    filename: str | None,
    name: str | None,
    declared_format: Format | None,
    field_mapping: dict[str, str] | None,
    demo_dataset: str | None = None,
) -> ImportRecord:
    result = ingest_bytes(
        content,
        filename=filename,
        declared_format=declared_format,
        field_mapping=field_mapping,
        limits=limits_from(settings),
    )
    with session.begin():
        record = import_repo.create_import(
            session,
            name=(name or filename or demo_dataset or "Untitled import")[:200],
            source_filename=filename,
            demo_dataset=demo_dataset,
            size_bytes=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(),
            summary=result.summary,
            events=result.events,
        )
    return record


def purge_expired_imports(session: Session, settings: Settings) -> int:
    """Delete imports older than the retention window (no-op when retention is 0)."""
    if settings.retention_hours <= 0:
        return 0
    cutoff = utcnow() - timedelta(hours=settings.retention_hours)
    with session.begin():
        return import_repo.purge_imports_older_than(session, cutoff)
