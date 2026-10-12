"""Deterministic event correlation.

Correlation rules (see docs/analysis.md for the full discussion):

1. **Trace ancestry.** Events sharing a ``trace_id`` belong to one request. An event whose
   ``parent_span_id`` matches a span in the same trace is a child of that span. When the
   parent span belongs to another service, that is an observed call ``parent -> child``.
2. **Explicit dependency calls.** ``dependency_call``, ``timeout`` and ``retry`` events
   with a ``target_service`` are observed calls ``service -> target_service``. The target
   may never emit events itself (an external API); it then appears as an *inferred* node.
3. **Request IDs.** Events sharing a ``request_id`` (but no trace) are grouped as related.
4. **Error propagation.** In a trace, an error in a child span followed by an error in its
   parent span (in another service) is a propagation ``child -> parent``. A failed
   dependency call is a propagation ``target -> caller``.
5. **Temporal proximity is never causal.** Events that are merely close in time are not
   linked here. The detector may use timing to group symptoms, and the ranker uses onset
   order as one weighted signal, but no edge or propagation is created from timing alone.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.schemas.events import CanonicalEvent, EventType

CALL_EVENT_TYPES = frozenset({EventType.DEPENDENCY_CALL, EventType.TIMEOUT})
_MAX_EDGE_EVIDENCE = 25


@dataclass
class EdgeEvidence:
    source: str
    target: str
    call_count: int = 0
    error_count: int = 0
    retry_count: int = 0
    durations_ms: list[float] = field(default_factory=list)
    evidence_event_ids: list[str] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)
    first_error_event_id: str | None = None

    def add_evidence(self, event_id: str) -> None:
        if len(self.evidence_event_ids) < _MAX_EDGE_EVIDENCE:
            self.evidence_event_ids.append(event_id)


@dataclass(frozen=True)
class Propagation:
    """A failure observed in ``from_service`` followed by a failure in ``to_service``."""

    from_service: str
    to_service: str
    from_event_id: str
    to_event_id: str
    trace_id: str | None
    basis: str  # "trace_parent" | "dependency_call"


@dataclass
class TraceSummary:
    trace_id: str
    event_ids: list[str] = field(default_factory=list)
    services: set[str] = field(default_factory=set)
    error_event_ids: list[str] = field(default_factory=list)
    orphan_span_ids: set[str] = field(default_factory=set)
    origin_service: str | None = None
    origin_event_id: str | None = None


@dataclass
class CorrelationResult:
    events_by_id: dict[str, CanonicalEvent]
    traces: dict[str, TraceSummary]
    edges: dict[tuple[str, str], EdgeEvidence]
    propagations: list[Propagation]
    request_groups: dict[str, list[str]]
    observed_services: set[str]
    inferred_services: set[str]
    traced_event_count: int
    orphan_span_count: int
    span_count: int
    # Error events whose span has an erroring child span (the error is explained downstream).
    explained_error_ids: set[str] = field(default_factory=set)

    @property
    def orphan_ratio(self) -> float:
        return self.orphan_span_count / self.span_count if self.span_count else 0.0

    def related_event_ids(self, event_id: str, limit: int = 50) -> list[str]:
        """Events sharing the trace or request of ``event_id`` (excluding itself)."""
        event = self.events_by_id.get(event_id)
        if event is None:
            return []
        related: list[str] = []
        if event.trace_id and event.trace_id in self.traces:
            related = list(self.traces[event.trace_id].event_ids)
        elif event.request_id and event.request_id in self.request_groups:
            related = list(self.request_groups[event.request_id])
        return [other for other in related if other != event_id][:limit]


def correlate(events: Sequence[CanonicalEvent]) -> CorrelationResult:
    events_by_id = {event.event_id: event for event in events}
    traces: dict[str, TraceSummary] = {}
    spans: dict[tuple[str, str], list[CanonicalEvent]] = defaultdict(list)
    request_groups: dict[str, list[str]] = defaultdict(list)
    observed_services = {event.service for event in events}
    traced = 0

    for event in events:
        if event.trace_id:
            traced += 1
            summary = traces.setdefault(event.trace_id, TraceSummary(event.trace_id))
            summary.event_ids.append(event.event_id)
            summary.services.add(event.service)
            if event.is_error:
                summary.error_event_ids.append(event.event_id)
            if event.span_id:
                spans[(event.trace_id, event.span_id)].append(event)
        elif event.request_id:
            request_groups[event.request_id].append(event.event_id)

    edges: dict[tuple[str, str], EdgeEvidence] = {}
    propagations: list[Propagation] = []
    seen_child_spans: set[tuple[str, str, str]] = set()
    span_count = 0
    orphan_spans: set[tuple[str, str]] = set()
    erroring_spans: set[tuple[str, str]] = set()
    children: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)

    def edge(source: str, target: str) -> EdgeEvidence:
        key = (source, target)
        if key not in edges:
            edges[key] = EdgeEvidence(source=source, target=target)
        return edges[key]

    for (trace_id, span_id), span_events in spans.items():
        span_count += 1
        if any(event.is_error for event in span_events):
            erroring_spans.add((trace_id, span_id))
        parent_id = next((e.parent_span_id for e in span_events if e.parent_span_id), None)
        if parent_id is None:
            continue
        parent_events = spans.get((trace_id, parent_id))
        if not parent_events:
            orphan_spans.add((trace_id, span_id))
            traces[trace_id].orphan_span_ids.add(span_id)
            continue
        children[(trace_id, parent_id)].append((trace_id, span_id))
        child_service = span_events[0].service
        parent_service = parent_events[0].service
        if child_service == parent_service:
            continue
        key = (parent_service, child_service, f"{trace_id}/{span_id}")
        if key in seen_child_spans:
            continue
        seen_child_spans.add(key)
        evidence = edge(parent_service, child_service)
        evidence.sources.add("trace")
        evidence.call_count += 1
        child_error = next((e for e in span_events if e.is_error), None)
        durations = [e.duration_ms for e in span_events if e.duration_ms is not None]
        if durations:
            evidence.durations_ms.append(max(durations))
        evidence.add_evidence(span_events[0].event_id)
        if child_error is not None:
            evidence.error_count += 1
            evidence.first_error_event_id = evidence.first_error_event_id or child_error.event_id
            parent_error = next(
                (e for e in parent_events if e.is_error and e.timestamp >= child_error.timestamp),
                None,
            )
            if parent_error is not None:
                propagations.append(
                    Propagation(
                        from_service=child_service,
                        to_service=parent_service,
                        from_event_id=child_error.event_id,
                        to_event_id=parent_error.event_id,
                        trace_id=trace_id,
                        basis="trace_parent",
                    )
                )

    for event in events:
        if not event.target_service or event.target_service == event.service:
            continue
        evidence = edge(event.service, event.target_service)
        evidence.sources.add("dependency_call" if event.event_type != EventType.RETRY else "retry")
        if event.event_type == EventType.RETRY:
            evidence.retry_count += 1
            evidence.add_evidence(event.event_id)
            continue
        if event.event_type not in CALL_EVENT_TYPES:
            evidence.add_evidence(event.event_id)
            continue
        evidence.call_count += 1
        if event.duration_ms is not None:
            evidence.durations_ms.append(event.duration_ms)
        evidence.add_evidence(event.event_id)
        if event.is_error:
            evidence.error_count += 1
            evidence.first_error_event_id = evidence.first_error_event_id or event.event_id
            propagations.append(
                Propagation(
                    from_service=event.target_service,
                    to_service=event.service,
                    from_event_id=event.event_id,
                    to_event_id=event.event_id,
                    trace_id=event.trace_id,
                    basis="dependency_call",
                )
            )

    _assign_trace_origins(traces, spans, children, erroring_spans)

    explained: set[str] = set()
    for span_key in erroring_spans:
        if any(child in erroring_spans for child in children.get(span_key, ())):
            explained.update(event.event_id for event in spans[span_key] if event.is_error)

    inferred = {target for (_, target) in edges} - observed_services
    return CorrelationResult(
        events_by_id=events_by_id,
        traces=traces,
        edges=edges,
        propagations=propagations,
        request_groups=dict(request_groups),
        observed_services=observed_services,
        inferred_services=inferred,
        traced_event_count=traced,
        orphan_span_count=len(orphan_spans),
        span_count=span_count,
        explained_error_ids=explained,
    )


def _assign_trace_origins(
    traces: dict[str, TraceSummary],
    spans: dict[tuple[str, str], list[CanonicalEvent]],
    children: dict[tuple[str, str], list[tuple[str, str]]],
    erroring_spans: set[tuple[str, str]],
) -> None:
    """For each failing trace, find the deepest failing component.

    The origin is the target of the earliest failed dependency call inside the deepest
    erroring span (if any), otherwise that span's service. "Deepest" means an erroring span
    none of whose children errored.
    """
    erroring_by_trace: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in sorted(erroring_spans):
        erroring_by_trace[key[0]].append(key)
    for trace_id, summary in traces.items():
        if not summary.error_event_ids:
            continue
        leaves = [
            key
            for key in erroring_by_trace.get(trace_id, ())
            if not any(child in erroring_spans for child in children.get(key, ()))
        ]
        if not leaves:
            continue
        candidates: list[tuple[datetime, str, str]] = []
        for key in leaves:
            for event in spans[key]:
                if not event.is_error:
                    continue
                target = event.target_service if event.event_type in CALL_EVENT_TYPES else None
                candidates.append((event.timestamp, target or event.service, event.event_id))
        if candidates:
            candidates.sort(key=lambda item: (str(item[0]), item[2]))
            _, summary.origin_service, summary.origin_event_id = candidates[0]
