"""API schemas for execution comparisons."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Presence = Literal["both", "baseline_only", "target_only"]


class ExecutionRef(BaseModel):
    """An import, optionally narrowed to a time window or to an incident's window."""

    import_id: str = Field(max_length=32)
    incident_id: str | None = Field(default=None, max_length=32)
    start: datetime | None = None
    end: datetime | None = None
    label: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _check_window(self) -> ExecutionRef:
        if self.incident_id and (self.start or self.end):
            raise ValueError("use either incident_id or start/end, not both")
        if self.start and self.end and self.start >= self.end:
            raise ValueError("start must be before end")
        return self


class ComparisonRequest(BaseModel):
    baseline: ExecutionRef
    target: ExecutionRef


class ProfileSummaryOut(BaseModel):
    label: str
    start: datetime | None
    end: datetime | None
    event_count: int
    error_count: int
    minutes: float
    service_count: int


class OverallOut(BaseModel):
    baseline_error_rate: float | None
    target_error_rate: float | None
    error_rate_delta: float | None
    baseline_events_per_min: float | None
    target_events_per_min: float | None


class ServiceDiffOut(BaseModel):
    service: str
    presence: Presence
    baseline_events_per_min: float | None
    target_events_per_min: float | None
    baseline_error_rate: float | None
    target_error_rate: float | None
    error_rate_delta: float | None
    baseline_p95_ms: float | None
    target_p95_ms: float | None
    p95_ratio: float | None
    latency_note: str | None
    baseline_versions: list[str]
    target_versions: list[str]
    baseline_status: str | None
    target_status: str | None


class EdgeDiffOut(BaseModel):
    id: str
    presence: Presence
    baseline_calls: int
    target_calls: int
    baseline_error_rate: float | None
    target_error_rate: float | None


class FindingOut(BaseModel):
    kind: Literal["service_presence", "error_rate", "latency", "version", "dependency"]
    service: str
    magnitude: float
    text: str


class ComparisonOut(BaseModel):
    id: str
    created_at: datetime
    baseline_ref: ExecutionRef
    target_ref: ExecutionRef
    comparable: bool
    incomparable_reasons: list[str]
    warnings: list[str]
    service_overlap: float
    baseline: ProfileSummaryOut
    target: ProfileSummaryOut
    overall: OverallOut
    services: list[ServiceDiffOut]
    edges: list[EdgeDiffOut]
    findings: list[FindingOut]
