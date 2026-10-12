"""Stored comparison results (so reports can cite them)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, utcnow


def new_comparison_id() -> str:
    return f"cmp_{uuid.uuid4().hex[:16]}"


class ComparisonRecord(Base):
    __tablename__ = "comparisons"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_comparison_id)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    baseline_import_id: Mapped[str] = mapped_column(String(32), index=True)
    target_import_id: Mapped[str] = mapped_column(String(32), index=True)
    baseline_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    target_ref: Mapped[dict[str, Any]] = mapped_column(JSON)
    comparable: Mapped[bool] = mapped_column(Boolean)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
