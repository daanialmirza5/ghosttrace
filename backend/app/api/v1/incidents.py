"""Incident endpoints: list, detail, hypotheses, timeline, graph and evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.core.timeutil import as_utc
from app.repositories import imports as import_repo
from app.repositories import incidents as incident_repo
from app.schemas.common import Page
from app.schemas.events import EventType, Severity
from app.schemas.incidents import (
    EventDetailOut,
    EvidenceStatus,
    GraphOut,
    HypothesesOut,
    IncidentDetailOut,
    IncidentSummaryOut,
    TimelineCategory,
    TimelineOut,
)
from app.schemas.incidents import Severity as IncidentSeverity
from app.services import incidents as incident_service

router = APIRouter(tags=["incidents"])


@router.get("/incidents", response_model=Page[IncidentSummaryOut])
def list_incidents(
    session: SessionDep,
    import_id: Annotated[str | None, Query(max_length=32)] = None,
    severity: IncidentSeverity | None = None,
    evidence_status: EvidenceStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[IncidentSummaryOut]:
    rows, total = incident_repo.list_incidents(
        session,
        limit=limit,
        offset=offset,
        import_id=import_id,
        severity=severity,
        evidence_status=evidence_status,
    )
    return Page(
        items=[incident_service.summary_out(record, name) for record, name in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/incidents/{incident_id}", response_model=IncidentDetailOut)
def get_incident(incident_id: str, session: SessionDep) -> IncidentDetailOut:
    return incident_service.detail_out(session, incident_repo.get_incident(session, incident_id))


@router.get("/incidents/{incident_id}/hypotheses", response_model=HypothesesOut)
def get_hypotheses(incident_id: str, session: SessionDep) -> HypothesesOut:
    return incident_service.hypotheses_out(incident_repo.get_incident(session, incident_id))


@router.get("/incidents/{incident_id}/timeline", response_model=TimelineOut)
def get_timeline(
    incident_id: str,
    session: SessionDep,
    service: Annotated[list[str] | None, Query()] = None,
    severity: Annotated[list[Severity] | None, Query()] = None,
    category: Annotated[list[TimelineCategory] | None, Query()] = None,
    event_type: Annotated[list[EventType] | None, Query()] = None,
    start: datetime | None = None,
    end: datetime | None = None,
    evidence_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TimelineOut:
    record = incident_repo.get_incident(session, incident_id)
    return incident_service.timeline_out(
        session,
        record,
        services=service or (),
        severities=[item.value for item in severity or ()],
        categories=category or (),
        event_types=[item.value for item in event_type or ()],
        start=as_utc(start),
        end=as_utc(end),
        evidence_only=evidence_only,
        limit=limit,
        offset=offset,
    )


@router.get("/incidents/{incident_id}/graph", response_model=GraphOut)
def get_incident_graph(incident_id: str, session: SessionDep) -> GraphOut:
    return incident_service.incident_graph(
        session, incident_repo.get_incident(session, incident_id)
    )


@router.get("/incidents/{incident_id}/events/{event_id}", response_model=EventDetailOut)
def get_incident_event(incident_id: str, event_id: str, session: SessionDep) -> EventDetailOut:
    record = incident_repo.get_incident(session, incident_id)
    return incident_service.event_detail(session, record, event_id)


@router.get("/imports/{import_id}/graph", response_model=GraphOut)
def get_import_graph(import_id: str, session: SessionDep) -> GraphOut:
    return incident_service.import_graph(session, import_repo.get_import(session, import_id))
