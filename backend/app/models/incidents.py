"""Detected incidents and their stored analysis."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, utcnow


def new_incident_id() -> str:
    return f"inc_{uuid.uuid4().hex[:16]}"


class IncidentRecord(Base):
    __tablename__ = "incidents"
    __table_args__ = (Index("ix_incidents_import_ordinal", "import_id", "ordinal"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_incident_id)
    import_id: Mapped[str] = mapped_column(ForeignKey("imports.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    severity: Mapped[str] = mapped_column(String(16), index=True)
    evidence_status: Mapped[str] = mapped_column(String(16))
    evidence_summary: Mapped[str] = mapped_column(Text)
    detected_start: Mapped[datetime] = mapped_column(UTCDateTime())
    detected_end: Mapped[datetime] = mapped_column(UTCDateTime())
    window_start: Mapped[datetime] = mapped_column(UTCDateTime())
    window_end: Mapped[datetime] = mapped_column(UTCDateTime())
    services: Mapped[list[str]] = mapped_column(JSON, default=list)
    signals: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    hypotheses: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    excluded_candidates: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    missing_information: Mapped[list[str]] = mapped_column(JSON, default=list)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    peak_error_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    top_service: Mapped[str | None] = mapped_column(String(128))
    top_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
