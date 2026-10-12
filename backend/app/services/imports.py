"""Import orchestration: validate an upload, persist it, and analyse it."""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.base import utcnow
from app.models.imports import ImportRecord, new_import_id
from app.models.incidents import IncidentRecord
from app.repositories import imports as import_repo
from app.services.analysis import analyze
from app.services.incidents import build_incident_records
from app.services.ingestion import IngestionLimits, ingest_bytes
from app.services.ingestion.parsers import Format

logger = logging.getLogger("ghosttrace.imports")


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
    """Validate, store and analyse one file inside a single database transaction.

    If analysis raises, the import and its events are still stored with
    ``analysis_status="failed"`` so the user keeps the validated data.
    """
    result = ingest_bytes(
        content,
        filename=filename,
        declared_format=declared_format,
        field_mapping=field_mapping,
        limits=limits_from(settings),
    )
    import_id = new_import_id()
    analysis_status, analysis_error = "skipped", None
    analysis_ms: float | None = None
    data_quality: list[dict[str, object]] = []
    incidents: list[IncidentRecord] = []
    if result.events:
        try:
            analysis = analyze(result.events)
            incidents = build_incident_records(import_id, result.events, analysis)
            analysis_status, analysis_ms = "completed", round(analysis.duration_ms, 2)
            data_quality = [signal.as_dict() for signal in analysis.detection.data_quality]
        except Exception as exc:
            logger.exception("Analysis failed for import %s", import_id)
            analysis_status, incidents = "failed", []
            analysis_error = f"analysis failed: {type(exc).__name__}"

    with session.begin():
        record = import_repo.create_import(
            session,
            import_id=import_id,
            name=(name or filename or demo_dataset or "Untitled import")[:200],
            source_filename=filename,
            demo_dataset=demo_dataset,
            size_bytes=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(),
            summary=result.summary,
            events=result.events,
        )
        record.analysis_status = analysis_status
        record.analysis_error = analysis_error
        record.analysis_ms = analysis_ms
        record.data_quality = data_quality
        session.add_all(incidents)
    return record


def purge_expired_imports(session: Session, settings: Settings) -> int:
    """Delete imports older than the retention window (no-op when retention is 0)."""
    if settings.retention_hours <= 0:
        return 0
    cutoff = utcnow() - timedelta(hours=settings.retention_hours)
    with session.begin():
        return import_repo.purge_imports_older_than(session, cutoff)
