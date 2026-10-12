"""Persist analysis results and build incident views (timeline, graph, evidence)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.imports import ImportRecord
from app.models.incidents import IncidentRecord
from app.repositories import imports as import_repo
from app.repositories.imports import EventFilter
from app.schemas.events import CanonicalEvent, EventOut, EventType
from app.schemas.incidents import (
    EventDetailOut,
    EvidenceReferenceOut,
    GraphEdgeOut,
    GraphNodeOut,
    GraphOut,
    GraphScopeOut,
    HistogramBucketOut,
    HypothesesOut,
    IncidentDetailOut,
    IncidentSummaryOut,
    RankingMethodOut,
    SignalOut,
    TimelineCategory,
    TimelineItemOut,
    TimelineMarkerOut,
    TimelineOut,
)
from app.services.analysis import AnalysisResult
from app.services.correlation import correlate
from app.services.graph_analysis import ServiceGraph, build_graph
from app.services.incident_detection.detector import is_timeout
from app.services.root_cause.ranker import PENALTIES, WEIGHTS


class EvidenceIntegrityError(RuntimeError):
    """An analysis referenced an event ID that does not exist in the import (a bug)."""


def referenced_event_ids(record: IncidentRecord) -> set[str]:
    ids: set[str] = set()
    for signal in record.signals:
        ids.update(signal.get("evidence_event_ids", []))
    for hypothesis in record.hypotheses:
        ids.update(hypothesis.get("supporting_event_ids", []))
        if hypothesis.get("key_event_id"):
            ids.add(hypothesis["key_event_id"])
        for part in (*hypothesis.get("signals", []), *hypothesis.get("contradictions", [])):
            ids.update(part.get("evidence_event_ids", []))
    return ids


def build_incident_records(
    import_id: str,
    events: Sequence[CanonicalEvent],
    analysis: AnalysisResult,
) -> list[IncidentRecord]:
    """Convert an analysis into incident rows, verifying every referenced event ID exists."""
    known = {event.event_id for event in events}
    incidents: list[IncidentRecord] = []
    for ordinal, item in enumerate(analysis.incidents, start=1):
        draft, ranking = item.draft, item.ranking
        top = ranking.hypotheses[0] if ranking.hypotheses else None
        incident = IncidentRecord(
            import_id=import_id,
            ordinal=ordinal,
            title=draft.title,
            severity=draft.severity,
            evidence_status=ranking.evidence_status,
            evidence_summary=ranking.evidence_summary,
            detected_start=draft.start,
            detected_end=draft.end,
            window_start=item.window_start,
            window_end=item.window_end,
            services=draft.services,
            signals=[signal.as_dict() for signal in draft.signals],
            hypotheses=[hypothesis.as_dict() for hypothesis in ranking.hypotheses],
            excluded_candidates=ranking.excluded_candidates,
            missing_information=ranking.missing_information,
            error_count=draft.error_count,
            event_count=item.event_count,
            peak_error_ratio=draft.peak_error_ratio,
            top_service=top.service if top else None,
            top_score=top.score if top else None,
        )
        unknown = referenced_event_ids(incident) - known
        if unknown:
            raise EvidenceIntegrityError(
                f"analysis referenced {len(unknown)} unknown event IDs, e.g. {sorted(unknown)[:3]}"
            )
        incidents.append(incident)
    return incidents


def summary_out(record: IncidentRecord, import_name: str) -> IncidentSummaryOut:
    return IncidentSummaryOut(
        id=record.id,
        import_id=record.import_id,
        import_name=import_name,
        ordinal=record.ordinal,
        title=record.title,
        severity=record.severity,
        evidence_status=record.evidence_status,
        detected_start=record.detected_start,
        detected_end=record.detected_end,
        window_start=record.window_start,
        window_end=record.window_end,
        services=record.services,
        error_count=record.error_count,
        event_count=record.event_count,
        peak_error_ratio=record.peak_error_ratio,
        top_service=record.top_service,
        top_score=record.top_score,
        signal_count=len(record.signals),
    )


def detail_out(session: Session, record: IncidentRecord) -> IncidentDetailOut:
    parent = import_repo.get_import(session, record.import_id)
    summary = summary_out(record, parent.name)
    return IncidentDetailOut(
        **summary.model_dump(),
        evidence_summary=record.evidence_summary,
        signals=[SignalOut.model_validate(signal) for signal in record.signals],
        hypotheses=record.hypotheses,
        excluded_candidates=record.excluded_candidates,
        missing_information=record.missing_information,
        data_quality=[SignalOut.model_validate(signal) for signal in parent.data_quality or []],
    )


RANKING_METHOD = RankingMethodOut(
    description=(
        "Each candidate's heuristic score is the weighted sum of six signal values in [0, 1] "
        "minus penalties for contradictory evidence, clipped to [0, 1]. The score orders "
        "candidates within this incident only; it is not calibrated and is not a probability."
    ),
    weights=WEIGHTS,
    penalties=PENALTIES,
)


def hypotheses_out(record: IncidentRecord) -> HypothesesOut:
    return HypothesesOut(
        incident_id=record.id,
        evidence_status=record.evidence_status,
        evidence_summary=record.evidence_summary,
        hypotheses=record.hypotheses,
        excluded_candidates=record.excluded_candidates,
        missing_information=record.missing_information,
        method=RANKING_METHOD,
    )


def window_events(session: Session, record: IncidentRecord) -> list[CanonicalEvent]:
    return import_repo.load_events(
        session, record.import_id, EventFilter(start=record.window_start, end=record.window_end)
    )


def category(event: CanonicalEvent) -> TimelineCategory:
    if event.event_type in (EventType.DEPLOYMENT, EventType.CONFIG_CHANGE):
        return "change"
    if event.event_type == EventType.RETRY:
        return "retry"
    if is_timeout(event) and event.is_warning_or_worse:
        return "timeout"
    if event.event_type == EventType.DEPENDENCY_CALL and event.is_error:
        return "dependency_failure"
    if event.is_error:
        return "error"
    if event.is_warning_or_worse:
        return "warning"
    if event.event_type in (EventType.SPAN, EventType.REQUEST):
        return "request"
    return "log"


def _event_out(event: CanonicalEvent) -> EventOut:
    return EventOut.model_validate(event.model_dump())


def timeline_out(
    session: Session,
    record: IncidentRecord,
    *,
    services: Sequence[str] = (),
    severities: Sequence[str] = (),
    categories: Sequence[str] = (),
    event_types: Sequence[str] = (),
    start: datetime | None = None,
    end: datetime | None = None,
    evidence_only: bool = False,
    limit: int = 500,
    offset: int = 0,
) -> TimelineOut:
    events = window_events(session, record)
    evidence = referenced_event_ids(record)
    all_services = sorted({event.service for event in events})
    category_counts: Counter[str] = Counter(category(event) for event in events)

    def keep(event: CanonicalEvent) -> bool:
        if services and event.service not in services:
            return False
        if severities and event.severity.value not in severities:
            return False
        if event_types and event.event_type.value not in event_types:
            return False
        if categories and category(event) not in categories:
            return False
        if start and event.timestamp < start:
            return False
        if end and event.timestamp > end:
            return False
        return not (evidence_only and event.event_id not in evidence)

    filtered = [event for event in events if keep(event)]
    page = filtered[offset : offset + limit]

    markers = [
        TimelineMarkerOut(
            kind="detected_start", time=record.detected_start, label="Incident detected (start)"
        ),
        TimelineMarkerOut(
            kind="detected_end", time=record.detected_end, label="Last anomalous signal"
        ),
    ]
    for signal in record.signals:
        markers.append(
            TimelineMarkerOut(
                kind="signal",
                time=datetime.fromisoformat(signal["start"]),
                label=signal["description"],
                ref_id=signal["id"],
            )
        )
    for event in events:
        if event.event_type in (EventType.DEPLOYMENT, EventType.CONFIG_CHANGE):
            markers.append(
                TimelineMarkerOut(
                    kind="change", time=event.timestamp, label=event.message, ref_id=event.event_id
                )
            )
    markers.sort(key=lambda marker: marker.time)

    return TimelineOut(
        incident_id=record.id,
        window_start=record.window_start,
        window_end=record.window_end,
        total=len(filtered),
        limit=limit,
        offset=offset,
        items=[
            TimelineItemOut(
                event=_event_out(event),
                category=category(event),
                is_evidence=event.event_id in evidence,
            )
            for event in page
        ],
        markers=markers,
        histogram=_histogram(filtered, record.window_start, record.window_end),
        services=all_services,
        categories=dict(category_counts),
    )


def _histogram(
    events: Sequence[CanonicalEvent], start: datetime, end: datetime, buckets: int = 60
) -> list[HistogramBucketOut]:
    span = max(1.0, (end - start).total_seconds())
    width = span / buckets
    rows = [[0, 0, 0] for _ in range(buckets)]
    for event in events:
        index = min(buckets - 1, max(0, int((event.timestamp - start).total_seconds() // width)))
        column = 0 if event.is_error else 1 if event.is_warning_or_worse else 2
        rows[index][column] += 1
    return [
        HistogramBucketOut(
            start=start + timedelta(seconds=index * width),
            errors=row[0],
            warnings=row[1],
            other=row[2],
        )
        for index, row in enumerate(rows)
    ]


def graph_out(
    graph: ServiceGraph,
    scope: GraphScopeOut,
    hypotheses: Sequence[dict[str, object]] = (),
) -> GraphOut:
    ranks: dict[str, tuple[int, float]] = {}
    for hypothesis in hypotheses:
        rank, score = hypothesis.get("rank"), hypothesis.get("score")
        if isinstance(rank, int) and isinstance(score, int | float):
            ranks[str(hypothesis.get("service"))] = (rank, float(score))
    nodes = []
    for name in sorted(graph.nodes):
        node = graph.nodes[name]
        rank = ranks.get(name)
        nodes.append(
            GraphNodeOut(
                id=name,
                kind=node.kind,
                status=node.status,
                event_count=node.event_count,
                error_count=node.error_count,
                warning_count=node.warning_count,
                error_rate=None if node.error_rate is None else round(node.error_rate, 4),
                latency_samples=node.latency_samples,
                p50_ms=node.p50_ms,
                p95_ms=node.p95_ms,
                versions=node.versions,
                depth=node.depth,
                sample_error_event_ids=node.sample_error_event_ids,
                hypothesis_rank=rank[0] if rank else None,
                hypothesis_score=rank[1] if rank else None,
            )
        )
    edges = [
        GraphEdgeOut(
            id=f"{edge.source}->{edge.target}",
            source=edge.source,
            target=edge.target,
            call_count=edge.call_count,
            error_count=edge.error_count,
            error_rate=None if edge.error_rate is None else round(edge.error_rate, 4),
            retry_count=edge.retry_count,
            p50_ms=edge.p50_ms,
            p95_ms=edge.p95_ms,
            evidence_types=edge.evidence_types,
            evidence_event_ids=edge.evidence_event_ids,
            in_cycle=edge.in_cycle,
        )
        for edge in graph.edges
    ]
    return GraphOut(
        scope=scope,
        nodes=nodes,
        edges=edges,
        cycles=graph.cycles,
        components=graph.components,
        entry_points=graph.entry_points,
    )


def incident_graph(session: Session, record: IncidentRecord) -> GraphOut:
    events = window_events(session, record)
    graph = build_graph(events, correlate(events))
    scope = GraphScopeOut(
        kind="incident",
        id=record.id,
        start=record.window_start,
        end=record.window_end,
        event_count=len(events),
    )
    return graph_out(graph, scope, record.hypotheses)


def import_graph(session: Session, record: ImportRecord) -> GraphOut:
    events = import_repo.load_events(session, record.id)
    graph = build_graph(events, correlate(events))
    scope = GraphScopeOut(
        kind="import",
        id=record.id,
        start=record.first_event_at,
        end=record.last_event_at,
        event_count=len(events),
    )
    return graph_out(graph, scope)


def event_detail(session: Session, record: IncidentRecord, event_id: str) -> EventDetailOut:
    row = import_repo.get_event(session, record.import_id, event_id)
    event = import_repo.to_canonical(row)
    relation = "none"
    related: list[CanonicalEvent] = []
    if event.trace_id:
        relation = "trace"
        rows, _ = import_repo.query_events(
            session, record.import_id, EventFilter(trace_id=event.trace_id), limit=51, offset=0
        )
        related = [import_repo.to_canonical(r) for r in rows if r.event_id != event_id][:50]
    elif event.request_id:
        relation = "request"
        rows, _ = import_repo.query_events(
            session, record.import_id, EventFilter(request_id=event.request_id), limit=51, offset=0
        )
        related = [import_repo.to_canonical(r) for r in rows if r.event_id != event_id][:50]

    references: list[EvidenceReferenceOut] = []
    for signal in record.signals:
        if event_id in signal.get("evidence_event_ids", []):
            references.append(
                EvidenceReferenceOut(kind="signal", ref=signal["id"], label=signal["description"])
            )
    for hypothesis in record.hypotheses:
        names = [
            part["name"]
            for part in (*hypothesis.get("signals", []), *hypothesis.get("contradictions", []))
            if event_id in part.get("evidence_event_ids", [])
        ]
        if names or event_id in hypothesis.get("supporting_event_ids", []):
            label = f"Hypothesis #{hypothesis['rank']} ({hypothesis['service']})"
            if names:
                label += ": " + ", ".join(names)
            references.append(
                EvidenceReferenceOut(kind="hypothesis", ref=str(hypothesis["rank"]), label=label)
            )
    return EventDetailOut(
        event=_event_out(event),
        relation=relation,
        related_events=[_event_out(item) for item in related],
        referenced_by=references,
    )
