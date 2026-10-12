"""End-to-end analysis of one import: correlate, detect, build graphs, rank hypotheses."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.schemas.events import CanonicalEvent
from app.services.correlation import CorrelationResult, correlate
from app.services.graph_analysis import ServiceGraph, build_graph
from app.services.incident_detection import (
    DetectionConfig,
    DetectionResult,
    IncidentDraft,
    detect_incidents,
)
from app.services.root_cause import RankingResult, rank_hypotheses

WINDOW_PADDING = timedelta(seconds=60)
WINDOW_LOOKBACK = timedelta(seconds=120)


@dataclass
class IncidentAnalysis:
    draft: IncidentDraft
    ranking: RankingResult
    graph: ServiceGraph
    window_start: datetime
    window_end: datetime
    event_count: int


@dataclass
class AnalysisResult:
    incidents: list[IncidentAnalysis]
    detection: DetectionResult
    correlation: CorrelationResult
    duration_ms: float


def incident_window(draft: IncidentDraft) -> tuple[datetime, datetime]:
    """Events shown for an incident: a short lookback before detection to a pad after."""
    return draft.start - WINDOW_LOOKBACK, draft.end + WINDOW_PADDING


def analyze(
    events: Sequence[CanonicalEvent], config: DetectionConfig | None = None
) -> AnalysisResult:
    started = time.perf_counter()
    ordered = sorted(events, key=lambda e: (e.timestamp, e.event_id))
    correlation = correlate(ordered)
    detection = detect_incidents(ordered, correlation, config)
    incidents: list[IncidentAnalysis] = []
    for draft in detection.incidents:
        window_start, window_end = incident_window(draft)
        window = [e for e in ordered if window_start <= e.timestamp <= window_end]
        window_correlation = correlate(window)
        graph = build_graph(window, window_correlation)
        ranking = rank_hypotheses(
            draft, ordered, window_correlation, graph, detection.change_points
        )
        incidents.append(
            IncidentAnalysis(
                draft=draft,
                ranking=ranking,
                graph=graph,
                window_start=window_start,
                window_end=window_end,
                event_count=len(window),
            )
        )
    return AnalysisResult(
        incidents=incidents,
        detection=detection,
        correlation=correlation,
        duration_ms=(time.perf_counter() - started) * 1000,
    )
