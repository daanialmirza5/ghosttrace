"""API schemas for incident replay."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.events import Severity
from app.schemas.incidents import TimelineCategory

NodeStatus = Literal["healthy", "degraded", "failing"]


class ReplayRequest(BaseModel):
    services: list[str] = Field(default_factory=list, max_length=100)
    severities: list[Severity] = Field(default_factory=list)
    categories: list[TimelineCategory] = Field(default_factory=list)
    max_frames: int = Field(default=5000, ge=1, le=5000)


class ReplayEdgeActivityOut(BaseModel):
    id: str
    failed: bool


class ReplayFrameOut(BaseModel):
    index: int
    event_id: str
    timestamp: datetime
    offset_ms: float
    service: str
    target_service: str | None
    severity: Severity
    category: TimelineCategory
    message: str
    node_updates: dict[str, NodeStatus]
    error_totals: dict[str, int]
    edge: ReplayEdgeActivityOut | None


class ReplayNodeOut(BaseModel):
    id: str
    kind: Literal["observed", "inferred"]
    depth: int | None


class ReplayEdgeOut(BaseModel):
    id: str
    source: str
    target: str


class ReplayFiltersOut(BaseModel):
    services: list[str]
    severities: list[str]
    categories: list[str]


class ReplayOut(BaseModel):
    replay_id: str
    incident_id: str
    frame_count: int
    total_events: int
    start: datetime | None
    end: datetime | None
    filters: ReplayFiltersOut
    nodes: list[ReplayNodeOut]
    edges: list[ReplayEdgeOut]
    initial_state: dict[str, NodeStatus]
    health_rules: dict[str, str | float]
    frames: list[ReplayFrameOut]
