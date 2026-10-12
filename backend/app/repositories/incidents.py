"""Data access for incidents."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models.imports import ImportRecord
from app.models.incidents import IncidentRecord


def get_incident(session: Session, incident_id: str) -> IncidentRecord:
    record = session.get(IncidentRecord, incident_id)
    if record is None:
        raise NotFoundError(f"Incident {incident_id!r} was not found.")
    return record


def list_incidents(
    session: Session,
    *,
    limit: int,
    offset: int,
    import_id: str | None = None,
    severity: str | None = None,
    evidence_status: str | None = None,
) -> tuple[list[tuple[IncidentRecord, str]], int]:
    query = select(IncidentRecord, ImportRecord.name).join(
        ImportRecord, ImportRecord.id == IncidentRecord.import_id
    )
    count = select(func.count()).select_from(IncidentRecord)
    filters = []
    if import_id:
        filters.append(IncidentRecord.import_id == import_id)
    if severity:
        filters.append(IncidentRecord.severity == severity)
    if evidence_status:
        filters.append(IncidentRecord.evidence_status == evidence_status)
    for condition in filters:
        query = query.where(condition)
        count = count.where(condition)
    rows = session.execute(
        query.order_by(IncidentRecord.created_at.desc(), IncidentRecord.ordinal)
        .limit(limit)
        .offset(offset)
    ).all()
    return [(row[0], row[1]) for row in rows], session.scalar(count) or 0


def incident_counts(session: Session, import_ids: Sequence[str]) -> dict[str, int]:
    if not import_ids:
        return {}
    rows = session.execute(
        select(IncidentRecord.import_id, func.count())
        .where(IncidentRecord.import_id.in_(list(import_ids)))
        .group_by(IncidentRecord.import_id)
    ).all()
    return {import_id: count for import_id, count in rows}
