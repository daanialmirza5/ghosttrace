"""Report endpoints: generate, fetch and download incident reports."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import SessionDep
from app.core.errors import NotFoundError, UnprocessableError
from app.models.base import utcnow
from app.models.comparisons import ComparisonRecord
from app.models.reports import ReportRecord
from app.repositories import incidents as incident_repo
from app.services.reporting import build_report_data, render_markdown

router = APIRouter(tags=["reports"])


class ReportRequest(BaseModel):
    format: Literal["markdown", "json"] = "markdown"
    comparison_id: str | None = Field(default=None, max_length=32)


class ReportOut(BaseModel):
    id: str
    incident_id: str
    import_id: str
    comparison_id: str | None
    format: Literal["markdown", "json"]
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    referenced_event_count: int
    created_at: datetime
    download_url: str
    content: str | None = None


def _out(record: ReportRecord, include_content: bool) -> ReportOut:
    return ReportOut(
        id=record.id,
        incident_id=record.incident_id,
        import_id=record.import_id,
        comparison_id=record.comparison_id,
        format=record.format,
        filename=record.filename,
        content_type=record.content_type,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        referenced_event_count=record.referenced_event_count,
        created_at=record.created_at,
        download_url=f"/api/v1/reports/{record.id}/download",
        content=record.content if include_content else None,
    )


@router.post(
    "/incidents/{incident_id}/reports",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
)
def create_report(incident_id: str, request: ReportRequest, session: SessionDep) -> ReportOut:
    """Generate a JSON or Markdown report. Every cited event ID is verified first."""
    incident = incident_repo.get_incident(session, incident_id)
    comparison = None
    if request.comparison_id:
        comparison = session.get(ComparisonRecord, request.comparison_id)
        if comparison is None:
            raise NotFoundError(f"Comparison {request.comparison_id!r} was not found.")
        if incident.import_id not in (comparison.baseline_import_id, comparison.target_import_id):
            raise UnprocessableError("the comparison does not involve this incident's import")

    generated_at = utcnow()
    data = build_report_data(session, incident, comparison=comparison, generated_at=generated_at)
    if request.format == "json":
        content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        content_type, extension = "application/json", "json"
    else:
        content = render_markdown(data)
        content_type, extension = "text/markdown; charset=utf-8", "md"
    encoded = content.encode("utf-8")
    record = ReportRecord(
        incident_id=incident.id,
        import_id=incident.import_id,
        comparison_id=comparison.id if comparison else None,
        format=request.format,
        filename=f"ghosttrace-{incident.id}-{generated_at:%Y%m%dT%H%M%SZ}.{extension}",
        content_type=content_type,
        content=content,
        sha256=hashlib.sha256(encoded).hexdigest(),
        size_bytes=len(encoded),
        referenced_event_count=data["event_id_check"]["verified"],
        created_at=generated_at,
    )
    session.add(record)
    session.commit()
    return _out(record, include_content=True)


@router.get("/incidents/{incident_id}/reports", response_model=list[ReportOut])
def list_reports(incident_id: str, session: SessionDep) -> list[ReportOut]:
    incident_repo.get_incident(session, incident_id)
    records = session.scalars(
        select(ReportRecord)
        .where(ReportRecord.incident_id == incident_id)
        .order_by(ReportRecord.created_at.desc())
    ).all()
    return [_out(record, include_content=False) for record in records]


def _get(session: SessionDep, report_id: str) -> ReportRecord:
    record = session.get(ReportRecord, report_id)
    if record is None:
        raise NotFoundError(f"Report {report_id!r} was not found.")
    return record


@router.get("/reports/{report_id}", response_model=ReportOut)
def get_report(report_id: str, session: SessionDep) -> ReportOut:
    return _out(_get(session, report_id), include_content=True)


@router.get("/reports/{report_id}/download")
def download_report(report_id: str, session: SessionDep) -> Response:
    record = _get(session, report_id)
    return Response(
        content=record.content.encode("utf-8"),
        media_type=record.content_type,
        headers={"Content-Disposition": f'attachment; filename="{record.filename}"'},
    )
