"""Data access for imports and events."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models.base import utcnow
from app.models.imports import EventRecord, ImportRecord
from app.schemas.events import CanonicalEvent, EventType, Severity
from app.services.ingestion import IngestionSummary

_INSERT_BATCH = 2_000


def create_import(
    session: Session,
    *,
    name: str,
    source_filename: str | None,
    demo_dataset: str | None,
    size_bytes: int,
    content_sha256: str,
    summary: IngestionSummary,
    events: Sequence[CanonicalEvent],
) -> ImportRecord:
    record = ImportRecord(
        name=name,
        source_filename=source_filename,
        demo_dataset=demo_dataset,
        format=summary.format,
        status=summary.status,
        size_bytes=size_bytes,
        content_sha256=content_sha256,
        total_records=summary.total_records,
        accepted_count=summary.accepted,
        rejected_count=summary.rejected,
        duplicate_count=summary.duplicates,
        warning_counts=dict(summary.warnings),
        errors=[error.as_dict() for error in summary.errors],
        errors_truncated=summary.errors_truncated,
        file_error=summary.file_error,
        first_event_at=summary.first_event_at,
        last_event_at=summary.last_event_at,
        services=summary.services,
        completed_at=utcnow(),
    )
    session.add(record)
    session.flush()
    rows = [{"import_id": record.id, **event.model_dump()} for event in events]
    for start in range(0, len(rows), _INSERT_BATCH):
        session.execute(insert(EventRecord), rows[start : start + _INSERT_BATCH])
    return record


def get_import(session: Session, import_id: str) -> ImportRecord:
    record = session.get(ImportRecord, import_id)
    if record is None:
        raise NotFoundError(f"Import {import_id!r} was not found.")
    return record


def list_imports(
    session: Session, *, limit: int, offset: int, status: str | None = None
) -> tuple[list[ImportRecord], int]:
    query = select(ImportRecord)
    count = select(func.count()).select_from(ImportRecord)
    if status:
        query = query.where(ImportRecord.status == status)
        count = count.where(ImportRecord.status == status)
    items = session.scalars(
        query.order_by(ImportRecord.created_at.desc(), ImportRecord.id).limit(limit).offset(offset)
    ).all()
    return list(items), session.scalar(count) or 0


def delete_import(session: Session, import_id: str) -> None:
    record = get_import(session, import_id)
    session.execute(delete(EventRecord).where(EventRecord.import_id == record.id))
    session.delete(record)


def purge_imports_older_than(session: Session, cutoff: datetime) -> int:
    ids = session.scalars(select(ImportRecord.id).where(ImportRecord.created_at < cutoff)).all()
    for import_id in ids:
        delete_import(session, import_id)
    return len(ids)


@dataclass(frozen=True)
class EventFilter:
    start: datetime | None = None
    end: datetime | None = None
    services: tuple[str, ...] = ()
    severities: tuple[str, ...] = ()
    event_types: tuple[str, ...] = ()
    trace_id: str | None = None
    search: str | None = None


def _apply_filter(query, import_id: str, flt: EventFilter):  # type: ignore[no-untyped-def]
    query = query.where(EventRecord.import_id == import_id)
    if flt.start is not None:
        query = query.where(EventRecord.timestamp >= flt.start)
    if flt.end is not None:
        query = query.where(EventRecord.timestamp <= flt.end)
    if flt.services:
        query = query.where(EventRecord.service.in_(flt.services))
    if flt.severities:
        query = query.where(EventRecord.severity.in_(flt.severities))
    if flt.event_types:
        query = query.where(EventRecord.event_type.in_(flt.event_types))
    if flt.trace_id:
        query = query.where(EventRecord.trace_id == flt.trace_id)
    if flt.search:
        escaped = flt.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.where(
            or_(
                EventRecord.message.ilike(pattern, escape="\\"),
                EventRecord.event_id.ilike(pattern, escape="\\"),
            )
        )
    return query


def query_events(
    session: Session, import_id: str, flt: EventFilter, *, limit: int, offset: int
) -> tuple[list[EventRecord], int]:
    items = session.scalars(
        _apply_filter(select(EventRecord), import_id, flt)
        .order_by(EventRecord.timestamp, EventRecord.event_id)
        .limit(limit)
        .offset(offset)
    ).all()
    total = session.scalar(
        _apply_filter(select(func.count()).select_from(EventRecord), import_id, flt)
    )
    return list(items), total or 0


def to_canonical(row: EventRecord) -> CanonicalEvent:
    # Rows were validated on the way in, so skip re-validation for speed.
    return CanonicalEvent.model_construct(
        event_id=row.event_id,
        timestamp=row.timestamp,
        service=row.service,
        environment=row.environment,
        severity=Severity(row.severity),
        event_type=EventType(row.event_type),
        message=row.message,
        trace_id=row.trace_id,
        span_id=row.span_id,
        parent_span_id=row.parent_span_id,
        request_id=row.request_id,
        deployment_version=row.deployment_version,
        duration_ms=row.duration_ms,
        status_code=row.status_code,
        target_service=row.target_service,
        error_type=row.error_type,
        attributes=dict(row.attributes or {}),
        event_id_derived=row.event_id_derived,
    )


def load_events(
    session: Session, import_id: str, flt: EventFilter | None = None
) -> list[CanonicalEvent]:
    rows = session.scalars(
        _apply_filter(select(EventRecord), import_id, flt or EventFilter()).order_by(
            EventRecord.timestamp, EventRecord.event_id
        )
    ).all()
    return [to_canonical(row) for row in rows]


def existing_event_ids(session: Session, import_id: str, event_ids: Iterable[str]) -> set[str]:
    wanted = list(set(event_ids))
    found: set[str] = set()
    for start in range(0, len(wanted), 500):
        chunk = wanted[start : start + 500]
        found.update(
            session.scalars(
                select(EventRecord.event_id).where(
                    EventRecord.import_id == import_id, EventRecord.event_id.in_(chunk)
                )
            ).all()
        )
    return found


def get_event(session: Session, import_id: str, event_id: str) -> EventRecord:
    row = session.scalar(
        select(EventRecord).where(
            EventRecord.import_id == import_id, EventRecord.event_id == event_id
        )
    )
    if row is None:
        raise NotFoundError(f"Event {event_id!r} was not found in import {import_id!r}.")
    return row
