"""Deterministic, evidence-linked root-cause hypothesis ranking.

Each candidate service receives six signal values in [0, 1]. The heuristic score is the
weighted sum of those values minus penalties for contradictory evidence, clipped to
[0, 1]. **The score is an uncalibrated ranking heuristic, not a probability**; it only
orders candidates within one incident. See docs/analysis.md for the rationale and the
known limitations of every signal.

Signals and weights:

=====================  ======  ==========================================================
temporal_precedence     0.20   how early the candidate's own anomalies began
trace_origin            0.20   share of failing traces whose deepest failure is here
dependency_position     0.15   share of other failing services that depend on it
change_proximity        0.15   a deployment/config change shortly before its anomalies
intrinsic_failure       0.15   errors not explained by a failing dependency
retry_amplification     0.15   share of the incident's retry traffic it generated
=====================  ======  ==========================================================
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from app.schemas.events import CanonicalEvent, EventType
from app.services.correlation import CorrelationResult
from app.services.graph_analysis import ServiceGraph
from app.services.incident_detection import ChangePoint, IncidentDraft, Signal

WEIGHTS: dict[str, float] = {
    "temporal_precedence": 0.20,
    "trace_origin": 0.20,
    "dependency_position": 0.15,
    "change_proximity": 0.15,
    "intrinsic_failure": 0.15,
    "retry_amplification": 0.15,
}
PENALTIES: dict[str, float] = {
    "downstream_failed_first": 0.15,
    "overload_under_retry_storm": 0.20,
    "errors_before_incident": 0.10,
}
CALL_TYPES = (EventType.DEPENDENCY_CALL, EventType.TIMEOUT)
_OVERLOAD = re.compile(r"overload|throttl|rate.?limit|too many requests|load shedding", re.I)
_MAX_EVIDENCE = 30
ONSET_LOOKBACK = timedelta(seconds=120)

EvidenceStatus = Literal["sufficient", "ambiguous", "insufficient"]
Uncertainty = Literal["low", "medium", "high"]


@dataclass
class SignalContribution:
    name: str
    weight: float
    value: float
    contribution: float
    explanation: str
    evidence_event_ids: list[str] = field(default_factory=list)


@dataclass
class Contradiction:
    name: str
    penalty: float
    explanation: str
    evidence_event_ids: list[str] = field(default_factory=list)


@dataclass
class Hypothesis:
    rank: int
    service: str
    candidate_kind: Literal["observed", "inferred"]
    statement: str
    score: float
    uncertainty: Uncertainty
    signals: list[SignalContribution]
    contradictions: list[Contradiction]
    missing_information: list[str]
    supporting_event_ids: list[str]
    key_event_id: str | None
    onset: datetime | None
    next_step: str

    def as_dict(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "service": self.service,
            "candidate_kind": self.candidate_kind,
            "statement": self.statement,
            "score": self.score,
            "score_label": "heuristic score (not a probability)",
            "uncertainty": self.uncertainty,
            "signals": [vars(s) for s in self.signals],
            "contradictions": [vars(c) for c in self.contradictions],
            "missing_information": self.missing_information,
            "supporting_event_ids": self.supporting_event_ids,
            "key_event_id": self.key_event_id,
            "onset": self.onset.isoformat() if self.onset else None,
            "next_step": self.next_step,
        }


@dataclass
class RankingResult:
    hypotheses: list[Hypothesis]
    evidence_status: EvidenceStatus
    evidence_summary: str
    missing_information: list[str]
    # Candidates that were scored but ended at 0 (listed so users can see what was ruled out).
    excluded_candidates: list[dict[str, str]] = field(default_factory=list)


def _onsets(
    events: Sequence[CanonicalEvent], start: datetime, end: datetime
) -> dict[str, tuple[datetime, str]]:
    """First sustained anomaly per service: >= 3 warning-or-worse events within 30 s.

    Outbound-call events describe the callee, so they are attributed to ``target_service``.
    """
    attributed: dict[str, list[CanonicalEvent]] = {}
    for event in events:
        if not (start - ONSET_LOOKBACK <= event.timestamp <= end):
            continue
        if not event.is_warning_or_worse or event.event_type in (
            EventType.DEPLOYMENT,
            EventType.CONFIG_CHANGE,
        ):
            continue
        owner = (
            event.target_service
            if event.target_service and event.event_type in (*CALL_TYPES, EventType.RETRY)
            else event.service
        )
        attributed.setdefault(owner, []).append(event)
    onsets: dict[str, tuple[datetime, str]] = {}
    window = timedelta(seconds=30)
    for service, items in attributed.items():
        for index, event in enumerate(items):
            if index + 2 < len(items) and items[index + 2].timestamp - event.timestamp <= window:
                onsets[service] = (event.timestamp, event.event_id)
                break
    return onsets


def rank_hypotheses(
    draft: IncidentDraft,
    events: Sequence[CanonicalEvent],
    correlation: CorrelationResult,
    graph: ServiceGraph,
    change_points: Sequence[ChangePoint],
    *,
    change_lookback: timedelta = timedelta(minutes=15),
    max_hypotheses: int = 5,
) -> RankingResult:
    start, end = draft.start, draft.end
    window_events = [e for e in events if start - ONSET_LOOKBACK <= e.timestamp <= end]
    signals_by_service: dict[str, list[Signal]] = {}
    for signal in draft.signals:
        signals_by_service.setdefault(signal.service, []).append(signal)
        if signal.target_service:
            signals_by_service.setdefault(signal.target_service, []).append(signal)

    relevant_changes = [
        point for point in change_points if start - change_lookback <= point.at <= end
    ]
    candidates = set(draft.services)
    candidates |= {
        name for name, node in graph.nodes.items() if node.status in ("failing", "degraded")
    }
    candidates |= {point.service for point in relevant_changes}
    candidates = {c for c in candidates if c in graph.nodes or c in signals_by_service}

    onsets = _onsets(window_events, start, end)
    onset_times = [onsets[c][0] for c in candidates if c in onsets]
    earliest = min(onset_times) if onset_times else start
    tau = max(30.0, (end - start).total_seconds() / 8)
    failing = {
        name
        for name in candidates
        if name in graph.nodes and graph.nodes[name].status in ("failing", "degraded")
    }

    # Trace origins inside the incident window.
    origin_counts: Counter[str] = Counter()
    origin_examples: dict[str, list[str]] = {}
    window_ids = {e.event_id for e in window_events}
    for trace in correlation.traces.values():
        if trace.origin_service and trace.origin_event_id in window_ids:
            origin_counts[trace.origin_service] += 1
            origin_examples.setdefault(trace.origin_service, []).append(trace.origin_event_id or "")
    failing_traces = sum(origin_counts.values())

    retry_events = [e for e in window_events if e.event_type == EventType.RETRY]
    storm_sources = {s.service for s in draft.signals if s.type == "retry_storm"}
    storm_targets = {s.target_service for s in draft.signals if s.type == "retry_storm"}
    storm_edges = {(s.service, s.target_service) for s in draft.signals if s.type == "retry_storm"}
    regression_changes = {
        str(s.metrics.get("change_event_id"))
        for s in draft.signals
        if s.type == "deployment_regression"
    }

    traced_ratio = (
        sum(1 for e in window_events if e.trace_id) / len(window_events) if window_events else 0.0
    )
    hypotheses: list[Hypothesis] = []
    for service in sorted(candidates):
        node = graph.nodes.get(service)
        kind: Literal["observed", "inferred"] = node.kind if node else "observed"
        contributions: list[SignalContribution] = []
        contradictions: list[Contradiction] = []
        missing: list[str] = []
        supporting: list[str] = []
        onset = onsets.get(service)

        # 1. Temporal precedence.
        if onset is not None:
            delta = (onset[0] - earliest).total_seconds()
            value = math.exp(-max(0.0, delta) / tau)
            text = (
                "earliest sustained anomaly among candidates"
                if delta <= 1
                else f"sustained anomalies began {delta:.0f}s after the earliest candidate"
            )
            contributions.append(_c("temporal_precedence", value, text, [onset[1]]))
            supporting.append(onset[1])
        else:
            contributions.append(
                _c("temporal_precedence", 0.0, "no sustained warning/error activity observed")
            )

        # 2. Trace origin.
        if failing_traces:
            share = origin_counts.get(service, 0) / failing_traces
            examples = origin_examples.get(service, [])[:10]
            contributions.append(
                _c(
                    "trace_origin",
                    share,
                    f"deepest failure in {origin_counts.get(service, 0)} of {failing_traces} "
                    "failing traces",
                    examples,
                )
            )
            supporting.extend(examples)
        else:
            contributions.append(_c("trace_origin", 0.0, "no failing traces with span ancestry"))

        # 3. Dependency position.
        others = failing - {service}
        dependents = graph.reachable(service, upstream=True) & others if node else set()
        value = len(dependents) / len(others) if others else 0.0
        dep_ids = [
            e.first_error_event_id or e.evidence_event_ids[0]
            for e in graph.edges
            if e.target == service and e.source in dependents and e.evidence_event_ids
        ][:10]
        contributions.append(
            _c(
                "dependency_position",
                value,
                f"{len(dependents)} of {len(others)} other affected services depend on it"
                + (f" ({', '.join(sorted(dependents))})" if dependents else ""),
                dep_ids,
            )
        )
        supporting.extend(dep_ids)

        # 4. Change proximity.
        reference = onset[0] if onset else start
        own_changes = [
            p
            for p in relevant_changes
            if p.service == service and p.at <= reference + timedelta(seconds=60)
        ]
        key_event_id: str | None = None
        if own_changes:
            change = max(own_changes, key=lambda p: p.at)
            gap = max(0.0, (reference - change.at).total_seconds())
            value = math.exp(-gap / 600.0)
            regressed = change.event_id in regression_changes
            if not regressed:
                value *= 0.4
            contributions.append(
                _c(
                    "change_proximity",
                    value,
                    f"{change.kind.replace('_', ' ')} {gap:.0f}s before its anomalies"
                    + (
                        "; followed by a measured error regression"
                        if regressed
                        else "; no error regression was measured in this service afterwards"
                    ),
                    [change.event_id],
                )
            )
            supporting.append(change.event_id)
            key_event_id = change.event_id
        else:
            contributions.append(
                _c("change_proximity", 0.0, "no change recorded before its anomalies")
            )

        # 5. Intrinsic failure.
        own_errors = [
            e
            for e in window_events
            if e.service == service
            and e.is_error
            and not (e.target_service and e.event_type in CALL_TYPES)
        ]
        self_errors = [e for e in own_errors if e.event_id not in correlation.explained_error_ids]
        calls_in = [
            e for e in window_events if e.target_service == service and e.event_type in CALL_TYPES
        ]
        failed_in = [e for e in calls_in if e.is_error]
        self_ratio = len(self_errors) / len(own_errors) if own_errors else 0.0
        target_ratio = len(failed_in) / len(calls_in) if len(failed_in) >= 3 else 0.0
        if traced_ratio < 0.2 and own_errors:
            self_ratio = min(self_ratio, 0.5)  # cannot tell own vs. inherited errors
        value = max(self_ratio * min(1.0, len(self_errors) / 5), target_ratio)
        parts = []
        if own_errors:
            parts.append(
                f"{len(self_errors)} of {len(own_errors)} own errors are not explained "
                "by a failing downstream span"
            )
        if failed_in:
            parts.append(f"{len(failed_in)} of {len(calls_in)} calls to it failed")
        evidence = [e.event_id for e in (self_errors[:6] + failed_in[:6])]
        contributions.append(
            _c(
                "intrinsic_failure",
                value,
                "; ".join(parts) or "no errors attributed to it",
                evidence,
            )
        )
        supporting.extend(evidence)
        if key_event_id is None and (self_errors or failed_in):
            key_event_id = (self_errors or failed_in)[0].event_id

        # 6. Retry amplification.
        own_retries = [e for e in retry_events if e.service == service]
        if service in storm_sources and retry_events:
            value = len(own_retries) / len(retry_events)
            ids = [e.event_id for e in own_retries[:8]]
            contributions.append(
                _c(
                    "retry_amplification",
                    value,
                    f"emitted {len(own_retries)} of {len(retry_events)} retries in the incident",
                    ids,
                )
            )
            supporting.extend(ids)
        else:
            contributions.append(_c("retry_amplification", 0.0, "no retry storm originating here"))

        # Contradictions.
        if onset is not None:
            for edge in graph.edges:
                if edge.source != service or edge.error_count < 3 or edge.target not in failing:
                    continue
                if (service, edge.target) in storm_edges:
                    # Failures this service is amplifying with its own retries do not
                    # exonerate it.
                    continue
                target_onset = onsets.get(edge.target)
                if target_onset is not None and target_onset[0] <= onset[0] + timedelta(seconds=5):
                    contradictions.append(
                        Contradiction(
                            "downstream_failed_first",
                            PENALTIES["downstream_failed_first"],
                            f"{edge.error_count} of its calls to {edge.target} failed, and "
                            f"{edge.target}'s anomalies began at or before its own",
                            [i for i in (edge.first_error_event_id, target_onset[1]) if i],
                        )
                    )
                    break
        if service in storm_targets and service not in storm_sources:
            overload = [e for e in self_errors if _is_overload(e)]
            if overload:
                contradictions.append(
                    Contradiction(
                        "overload_under_retry_storm",
                        PENALTIES["overload_under_retry_storm"],
                        f"{len(overload)} of its errors indicate overload/load shedding while a "
                        "retry storm was aimed at it, which suggests it is being amplified "
                        "rather than originating the failure",
                        [e.event_id for e in overload[:5]],
                    )
                )
        before = [
            e
            for e in events
            if e.service == service
            and e.is_error
            and start - timedelta(minutes=10) <= e.timestamp < start - ONSET_LOOKBACK
        ]
        if own_errors and before:
            before_rate = len(before) / max(
                1.0, (timedelta(minutes=10) - ONSET_LOOKBACK).total_seconds()
            )
            during_rate = len(own_errors) / max(1.0, (end - start + ONSET_LOOKBACK).total_seconds())
            if before_rate >= during_rate * 0.5:
                contradictions.append(
                    Contradiction(
                        "errors_before_incident",
                        PENALTIES["errors_before_incident"],
                        "it was already producing errors at a similar rate before the incident",
                        [e.event_id for e in before[:5]],
                    )
                )

        # Missing information.
        if kind == "inferred":
            callers = sorted({e.service for e in calls_in})
            missing.append(
                f"{service} emits no events; its behaviour is inferred from {len(calls_in)} "
                f"calls made by {', '.join(callers) or 'other services'}"
            )
        if node is not None and node.latency_samples == 0:
            missing.append(f"no latency measurements for {service}")
        if kind == "observed" and own_errors and not any(e.trace_id for e in own_errors):
            missing.append(f"{service}'s error events carry no trace context")

        raw = sum(c.contribution for c in contributions)
        penalty = sum(c.penalty for c in contradictions)
        score = round(min(1.0, max(0.0, raw - penalty)), 3)
        hypotheses.append(
            Hypothesis(
                rank=0,
                service=service,
                candidate_kind=kind,
                statement="",
                score=score,
                uncertainty="high",
                signals=contributions,
                contradictions=contradictions,
                missing_information=missing,
                supporting_event_ids=_unique(supporting)[:_MAX_EVIDENCE],
                key_event_id=key_event_id,
                onset=onset[0] if onset else None,
                next_step="",
            )
        )

    hypotheses.sort(key=lambda h: (-h.score, h.onset or end, h.service))
    excluded = [
        {
            "service": h.service,
            "reason": "contradictory evidence outweighed its supporting signals"
            if h.contradictions
            else "no supporting signals",
        }
        for h in hypotheses
        if h.score <= 0
    ]
    hypotheses = [h for h in hypotheses if h.score > 0][:max_hypotheses]

    # Incident-level evidence assessment.
    structural = failing_traces >= 3 or any(
        e.error_count >= 3 and e.source in candidates and e.target in candidates
        for e in graph.edges
    )
    incident_missing: list[str] = []
    if traced_ratio < 0.2:
        incident_missing.append(
            f"only {traced_ratio:.0%} of events in the incident window carry a trace ID, so "
            "causal links between services cannot be reconstructed"
        )
    if not any(e.target_service for e in window_events):
        incident_missing.append("no events record a target_service, so dependencies are unknown")
    if not relevant_changes:
        incident_missing.append(
            "no deployment, configuration or version-change events were imported for the "
            "incident window"
        )
    if correlation.span_count and correlation.orphan_ratio >= 0.1:
        incident_missing.append(
            f"{correlation.orphan_ratio:.0%} of spans reference a parent span missing from "
            "the import"
        )

    status: EvidenceStatus
    top = hypotheses[0] if hypotheses else None
    second = hypotheses[1] if len(hypotheses) > 1 else None
    margin = (top.score - second.score) if top and second else (top.score if top else 0.0)
    if top is None or (not structural and not relevant_changes) or top.score < 0.3:
        status = "insufficient"
        summary = (
            "Insufficient evidence to rank a root cause: the affected services are not linked by "
            "trace ancestry, dependency calls or change events"
            if top is not None and not structural and not relevant_changes
            else "Insufficient evidence: no candidate reached the minimum heuristic score of 0.30"
        )
    elif margin < 0.05:
        status = "ambiguous"
        summary = (
            f"Ambiguous: {top.service} and {second.service if second else ''} have nearly equal "
            "heuristic scores"
        )
    else:
        status = "sufficient"
        summary = (
            f"{top.service} ranks highest (heuristic score {top.score:.2f}, margin "
            f"{margin:.2f} over the next candidate). This is a ranked hypothesis, not proof."
        )

    for index, hypothesis in enumerate(hypotheses, start=1):
        hypothesis.rank = index
        hypothesis.statement = f"The incident originated in {hypothesis.service}" + (
            " (inferred dependency)" if hypothesis.candidate_kind == "inferred" else ""
        )
        hypothesis.uncertainty = _uncertainty(hypothesis, index, status, margin)
        hypothesis.next_step = _next_step(hypothesis, status, draft, change_points)

    return RankingResult(
        hypotheses=hypotheses,
        evidence_status=status,
        evidence_summary=summary,
        missing_information=incident_missing,
        excluded_candidates=excluded,
    )


def _c(name: str, value: float, explanation: str, ids: Sequence[str] = ()) -> SignalContribution:
    value = round(max(0.0, min(1.0, value)), 3)
    weight = WEIGHTS[name]
    return SignalContribution(
        name=name,
        weight=weight,
        value=value,
        contribution=round(weight * value, 4),
        explanation=explanation,
        evidence_event_ids=[i for i in ids if i][:10],
    )


def _unique(ids: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for event_id in ids:
        if event_id and event_id not in seen:
            seen.add(event_id)
            ordered.append(event_id)
    return ordered


def _is_overload(event: CanonicalEvent) -> bool:
    text = f"{event.error_type or ''} {event.message}"
    return event.status_code in (429, 503) or bool(_OVERLOAD.search(text))


def _uncertainty(h: Hypothesis, rank: int, status: EvidenceStatus, margin: float) -> Uncertainty:
    if status != "sufficient" or h.score < 0.35:
        return "high"
    if rank == 1 and h.score >= 0.55 and margin >= 0.15 and not h.contradictions:
        return "low"
    return "medium"


def _next_step(
    h: Hypothesis,
    status: EvidenceStatus,
    draft: IncidentDraft,
    change_points: Sequence[ChangePoint],
) -> str:
    by_name = {s.name: s for s in h.signals}
    if status == "insufficient":
        return (
            "Collect more evidence before acting: enable trace propagation (trace_id/span_id), "
            "record target_service on outbound calls, and correlate with infrastructure or "
            f"network logs for the window {draft.start:%H:%M:%S}-{draft.end:%H:%M:%S} UTC."
        )
    if by_name["retry_amplification"].value >= 0.5:
        return (
            f"Review {h.service}'s retry policy (attempt limit, backoff, jitter) and add a circuit "
            "breaker; check whether reverting its most recent configuration change stops the storm."
        )
    if by_name["change_proximity"].value > 0 and h.key_event_id:
        change = next((p for p in change_points if p.event_id == h.key_event_id), None)
        version = (
            f" {change.previous_version} -> {change.new_version}"
            if change and change.new_version
            else ""
        )
        return (
            f"Review the {h.service} change{version} (event {h.key_event_id}); compare error rates "
            "before and after it and consider rolling it back to confirm."
        )
    if h.candidate_kind == "inferred":
        return (
            f"{h.service} is only visible through its callers: check its status page or provider "
            "metrics, and confirm the client timeout and failure mode from the failed calls."
        )
    if h.key_event_id:
        return (
            f"Inspect {h.service} around {h.onset:%H:%M:%S} UTC starting from event "
            f"{h.key_event_id}; "
            "check resource limits (connections, memory, CPU) and its own dependencies."
            if h.onset
            else f"Inspect {h.service} starting from event {h.key_event_id}."
        )
    return f"Inspect {h.service}'s logs and metrics for the incident window."
