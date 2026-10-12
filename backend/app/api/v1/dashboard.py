"""Dashboard summary computed from stored imports and incidents."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import SessionDep
from app.models.imports import EventRecord, ImportRecord
from app.models.incidents import IncidentRecord
from app.repositories import incidents as incident_repo
from app.schemas.incidents import IncidentSummaryOut
from app.services import incidents as incident_service

router = APIRouter(tags=["dashboard"])


class RecentImportOut(BaseModel):
    id: str
    name: str
    status: str
    created_at: datetime
    accepted: int
    rejected: int
    incident_count: int


class DashboardOut(BaseModel):
    import_count: int
    event_count: int
    rejected_record_count: int
    incident_count: int
    incidents_by_severity: dict[str, int]
    incidents_by_evidence_status: dict[str, int]
    top_ranked_services: dict[str, int]
    average_analysis_ms: float | None
    recent_incidents: list[IncidentSummaryOut]
    recent_imports: list[RecentImportOut]


@router.get("/dashboard/summary", response_model=DashboardOut)
def dashboard_summary(session: SessionDep) -> DashboardOut:
    import_count = session.scalar(select(func.count()).select_from(ImportRecord)) or 0
    event_count = session.scalar(select(func.count()).select_from(EventRecord)) or 0
    rejected = session.scalar(select(func.coalesce(func.sum(ImportRecord.rejected_count), 0))) or 0
    average_ms = session.scalar(
        select(func.avg(ImportRecord.analysis_ms)).where(ImportRecord.analysis_ms.is_not(None))
    )
    rows = session.execute(
        select(IncidentRecord.severity, IncidentRecord.evidence_status, IncidentRecord.top_service)
    ).all()
    by_severity = Counter(row[0] for row in rows)
    by_status = Counter(row[1] for row in rows)
    top_services = Counter(row[2] for row in rows if row[2] and row[1] != "insufficient")

    recent, _ = incident_repo.list_incidents(session, limit=5, offset=0)
    imports = session.scalars(
        select(ImportRecord).order_by(ImportRecord.created_at.desc()).limit(5)
    ).all()
    counts = incident_repo.incident_counts(session, [item.id for item in imports])
    return DashboardOut(
        import_count=import_count,
        event_count=event_count,
        rejected_record_count=int(rejected),
        incident_count=len(rows),
        incidents_by_severity=dict(by_severity),
        incidents_by_evidence_status=dict(by_status),
        top_ranked_services=dict(top_services.most_common(5)),
        average_analysis_ms=round(float(average_ms), 1) if average_ms is not None else None,
        recent_incidents=[incident_service.summary_out(record, name) for record, name in recent],
        recent_imports=[
            RecentImportOut(
                id=item.id,
                name=item.name,
                status=item.status,
                created_at=item.created_at,
                accepted=item.accepted_count,
                rejected=item.rejected_count,
                incident_count=counts.get(item.id, 0),
            )
            for item in imports
        ],
    )
