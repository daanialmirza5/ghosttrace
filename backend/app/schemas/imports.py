"""API schemas for imports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.imports import ImportRecord

ImportStatus = Literal["completed", "completed_with_errors", "failed"]


class RecordErrorOut(BaseModel):
    position: int = Field(description="1-based line (JSONL/CSV) or array index (JSON)")
    kind: Literal["line", "record", "row"]
    message: str
    field: str | None


class ImportOut(BaseModel):
    id: str
    name: str
    source_filename: str | None
    demo_dataset: str | None
    format: str | None
    status: ImportStatus
    created_at: datetime
    completed_at: datetime | None
    size_bytes: int
    content_sha256: str
    total_records: int
    accepted: int
    rejected: int
    duplicates: int
    warnings: dict[str, int]
    errors: list[RecordErrorOut]
    errors_truncated: bool
    file_error: str | None
    first_event_at: datetime | None
    last_event_at: datetime | None
    services: list[str]
    analysis_status: Literal["pending", "completed", "failed", "skipped"]
    analysis_error: str | None
    analysis_ms: float | None
    incident_count: int = 0

    @classmethod
    def from_record(cls, record: ImportRecord, incident_count: int = 0) -> ImportOut:
        return cls(
            id=record.id,
            name=record.name,
            source_filename=record.source_filename,
            demo_dataset=record.demo_dataset,
            format=record.format,
            status=record.status,
            created_at=record.created_at,
            completed_at=record.completed_at,
            size_bytes=record.size_bytes,
            content_sha256=record.content_sha256,
            total_records=record.total_records,
            accepted=record.accepted_count,
            rejected=record.rejected_count,
            duplicates=record.duplicate_count,
            warnings=record.warning_counts or {},
            errors=[RecordErrorOut.model_validate(error) for error in record.errors or []],
            errors_truncated=record.errors_truncated,
            file_error=record.file_error,
            first_event_at=record.first_event_at,
            last_event_at=record.last_event_at,
            services=record.services or [],
            analysis_status=record.analysis_status,
            analysis_error=record.analysis_error,
            analysis_ms=record.analysis_ms,
            incident_count=incident_count,
        )


class DemoDatasetOut(BaseModel):
    name: str
    title: str
    summary: str
    filename: str
    format: Literal["jsonl", "json", "csv"]
    size_bytes: int
    field_mapping: dict[str, str] | None = None
