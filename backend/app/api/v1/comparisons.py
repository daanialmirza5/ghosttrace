"""Comparison endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import SessionDep
from app.core.errors import NotFoundError, UnprocessableError
from app.core.timeutil import as_utc
from app.models.comparisons import ComparisonRecord
from app.repositories import imports as import_repo
from app.repositories import incidents as incident_repo
from app.repositories.imports import EventFilter
from app.schemas.common import Page
from app.schemas.comparisons import ComparisonOut, ComparisonRequest, ExecutionRef
from app.services.comparison import ExecutionProfile, compare_profiles, profile_events

router = APIRouter(tags=["comparisons"])


def _profile(session: Session, ref: ExecutionRef, default_label: str) -> ExecutionProfile:
    record = import_repo.get_import(session, ref.import_id)
    start, end = as_utc(ref.start), as_utc(ref.end)
    if ref.incident_id:
        incident = incident_repo.get_incident(session, ref.incident_id)
        if incident.import_id != record.id:
            raise UnprocessableError("incident_id does not belong to import_id")
        start, end = incident.window_start, incident.window_end
    events = import_repo.load_events(session, record.id, EventFilter(start=start, end=end))
    return profile_events(ref.label or default_label, events)


def _out(record: ComparisonRecord) -> ComparisonOut:
    return ComparisonOut.model_validate(
        {
            "id": record.id,
            "created_at": record.created_at,
            "baseline_ref": record.baseline_ref,
            "target_ref": record.target_ref,
            **record.result,
        }
    )


@router.post("/comparisons", response_model=ComparisonOut, status_code=status.HTTP_201_CREATED)
def create_comparison(request: ComparisonRequest, session: SessionDep) -> ComparisonOut:
    """Compare a baseline (e.g. healthy) execution with a target (e.g. failed) execution.

    Incomparable inputs are still answered: ``comparable`` is false and
    ``incomparable_reasons`` explains why, so no difference is reported silently.
    """
    baseline = _profile(session, request.baseline, "baseline")
    target = _profile(session, request.target, "target")
    result = compare_profiles(baseline, target)
    record = ComparisonRecord(
        baseline_import_id=request.baseline.import_id,
        target_import_id=request.target.import_id,
        baseline_ref=request.baseline.model_dump(mode="json"),
        target_ref=request.target.model_dump(mode="json"),
        comparable=result["comparable"],
        result=result,
    )
    session.add(record)
    session.commit()
    return _out(record)


@router.get("/comparisons", response_model=Page[ComparisonOut])
def list_comparisons(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ComparisonOut]:
    records = session.scalars(
        select(ComparisonRecord)
        .order_by(ComparisonRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    total = session.scalar(select(func.count()).select_from(ComparisonRecord)) or 0
    return Page(items=[_out(r) for r in records], total=total, limit=limit, offset=offset)


@router.get("/comparisons/{comparison_id}", response_model=ComparisonOut)
def get_comparison(comparison_id: str, session: SessionDep) -> ComparisonOut:
    record = session.get(ComparisonRecord, comparison_id)
    if record is None:
        raise NotFoundError(f"Comparison {comparison_id!r} was not found.")
    return _out(record)
