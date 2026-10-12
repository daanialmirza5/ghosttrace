"""Imports (uploaded datasets) and their normalised events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime, utcnow


def new_import_id() -> str:
    return f"imp_{uuid.uuid4().hex[:16]}"


class ImportRecord(Base):
    __tablename__ = "imports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_import_id)
    name: Mapped[str] = mapped_column(String(200))
    source_filename: Mapped[str | None] = mapped_column(String(255))
    demo_dataset: Mapped[str | None] = mapped_column(String(100))
    format: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    content_sha256: Mapped[str] = mapped_column(String(64))
    total_records: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_counts: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    errors_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    file_error: Mapped[str | None] = mapped_column(Text)
    first_event_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_event_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    services: Mapped[list[str]] = mapped_column(JSON, default=list)
    analysis_status: Mapped[str] = mapped_column(String(16), default="pending")
    analysis_error: Mapped[str | None] = mapped_column(Text)
    analysis_ms: Mapped[float | None] = mapped_column(Float)
    data_quality: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    events: Mapped[list[EventRecord]] = relationship(
        back_populates="import_record", cascade="all, delete-orphan", passive_deletes=True
    )


class EventRecord(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("import_id", "event_id", name="uq_events_import_event"),
        Index("ix_events_import_time", "import_id", "timestamp"),
        Index("ix_events_import_trace", "import_id", "trace_id"),
    )

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    import_id: Mapped[str] = mapped_column(ForeignKey("imports.id", ondelete="CASCADE"))
    event_id: Mapped[str] = mapped_column(String(128))
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    service: Mapped[str] = mapped_column(String(128))
    environment: Mapped[str] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(16))
    event_type: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text, default="")
    trace_id: Mapped[str | None] = mapped_column(String(128))
    span_id: Mapped[str | None] = mapped_column(String(128))
    parent_span_id: Mapped[str | None] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(128))
    deployment_version: Mapped[str | None] = mapped_column(String(128))
    duration_ms: Mapped[float | None] = mapped_column(Float)
    status_code: Mapped[int | None] = mapped_column(Integer)
    target_service: Mapped[str | None] = mapped_column(String(128))
    error_type: Mapped[str | None] = mapped_column(String(128))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    event_id_derived: Mapped[bool] = mapped_column(Boolean, default=False)

    import_record: Mapped[ImportRecord] = relationship(back_populates="events")
