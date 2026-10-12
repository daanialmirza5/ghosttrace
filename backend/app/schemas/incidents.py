"""API schemas for incidents, hypotheses, timelines and graphs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.events import EventOut

Severity = Literal["critical", "major", "minor"]
EvidenceStatus = Literal["sufficient", "ambiguous", "insufficient"]


class SignalOut(BaseModel):
    id: str
    type: str
    basis: Literal["observed", "inferred"]
    service: str
    target_service: str | None
    start: datetime
    end: datetime
    count: int
    description: str
    evidence_event_ids: list[str]
    metrics: dict[str, float | int | str]


class SignalContributionOut(BaseModel):
    name: str
    weight: float
    value: float
    contribution: float
    explanation: str
    evidence_event_ids: list[str]


class ContradictionOut(BaseModel):
    name: str
    penalty: float
    explanation: str
    evidence_event_ids: list[str]


class HypothesisOut(BaseModel):
    rank: int
    service: str
    candidate_kind: Literal["observed", "inferred"]
    statement: str
    score: float = Field(description="Uncalibrated heuristic ranking score; not a probability.")
    score_label: str
    uncertainty: Literal["low", "medium", "high"]
    signals: list[SignalContributionOut]
    contradictions: list[ContradictionOut]
    missing_information: list[str]
    supporting_event_ids: list[str]
    key_event_id: str | None
    onset: datetime | None
    next_step: str


class ExcludedCandidateOut(BaseModel):
    service: str
    reason: str


class IncidentSummaryOut(BaseModel):
    id: str
    import_id: str
    import_name: str
    ordinal: int
    title: str
    severity: Severity
    evidence_status: EvidenceStatus
    detected_start: datetime
    detected_end: datetime
    window_start: datetime
    window_end: datetime
    services: list[str]
    error_count: int
    event_count: int
    peak_error_ratio: float
    top_service: str | None
    top_score: float | None
    signal_count: int


class IncidentDetailOut(IncidentSummaryOut):
    evidence_summary: str
    signals: list[SignalOut]
    hypotheses: list[HypothesisOut]
    excluded_candidates: list[ExcludedCandidateOut]
    missing_information: list[str]
    data_quality: list[SignalOut]


class RankingMethodOut(BaseModel):
    description: str
    weights: dict[str, float]
    penalties: dict[str, float]


class HypothesesOut(BaseModel):
    incident_id: str
    evidence_status: EvidenceStatus
    evidence_summary: str
    hypotheses: list[HypothesisOut]
    excluded_candidates: list[ExcludedCandidateOut]
    missing_information: list[str]
    method: RankingMethodOut


TimelineCategory = Literal[
    "error",
    "warning",
    "request",
    "change",
    "retry",
    "timeout",
    "dependency_failure",
    "log",
]


class TimelineItemOut(BaseModel):
    event: EventOut
    category: TimelineCategory
    is_evidence: bool


class TimelineMarkerOut(BaseModel):
    kind: Literal["detected_start", "detected_end", "signal", "change"]
    time: datetime
    label: str
    ref_id: str | None = None


class HistogramBucketOut(BaseModel):
    start: datetime
    errors: int
    warnings: int
    other: int


class TimelineOut(BaseModel):
    incident_id: str
    window_start: datetime
    window_end: datetime
    total: int
    limit: int
    offset: int
    items: list[TimelineItemOut]
    markers: list[TimelineMarkerOut]
    histogram: list[HistogramBucketOut]
    services: list[str]
    categories: dict[str, int]


class GraphNodeOut(BaseModel):
    id: str
    kind: Literal["observed", "inferred"]
    status: Literal["healthy", "degraded", "failing", "unknown"]
    event_count: int
    error_count: int
    warning_count: int
    error_rate: float | None
    latency_samples: int
    p50_ms: float | None
    p95_ms: float | None
    versions: list[str]
    depth: int | None
    sample_error_event_ids: list[str]
    hypothesis_rank: int | None = None
    hypothesis_score: float | None = None


class GraphEdgeOut(BaseModel):
    id: str
    source: str
    target: str
    call_count: int
    error_count: int
    error_rate: float | None
    retry_count: int
    p50_ms: float | None
    p95_ms: float | None
    evidence_types: list[str]
    evidence_event_ids: list[str]
    in_cycle: bool


class GraphScopeOut(BaseModel):
    kind: Literal["incident", "import"]
    id: str
    start: datetime | None
    end: datetime | None
    event_count: int


class GraphOut(BaseModel):
    scope: GraphScopeOut
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    cycles: list[list[str]]
    components: int
    entry_points: list[str]


class EvidenceReferenceOut(BaseModel):
    kind: Literal["hypothesis", "signal"]
    ref: str
    label: str


class EventDetailOut(BaseModel):
    event: EventOut
    relation: Literal["trace", "request", "none"]
    related_events: list[EventOut]
    referenced_by: list[EvidenceReferenceOut]
