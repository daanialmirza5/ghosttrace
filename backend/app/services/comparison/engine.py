"""Healthy-versus-failed execution comparison.

Two executions (an import, optionally narrowed to a time window) are profiled and
compared. Rates are normalised per minute so windows of different lengths can be
compared. Latency is compared only where *both* sides have measurements; otherwise the
row says "not measured" instead of reporting a misleading zero.

Comparability checks (reported, never silently ignored):

* both sides need at least ``MIN_EVENTS`` events and ``MIN_SECONDS`` of data;
* the service sets must overlap (Jaccard similarity >= ``MIN_SERVICE_OVERLAP``);
* very different window lengths or traffic volumes produce warnings.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.schemas.events import CanonicalEvent
from app.services.correlation import correlate
from app.services.graph_analysis import build_graph
from app.services.incident_detection.detector import measured_service
from app.services.incident_detection.stats import quantile

MIN_EVENTS = 20
MIN_SECONDS = 30.0
MIN_SERVICE_OVERLAP = 0.3


@dataclass
class ServiceProfile:
    events: int = 0
    errors: int = 0
    latencies: list[float] = field(default_factory=list)
    versions: set[str] = field(default_factory=set)
    status: str = "unknown"


@dataclass
class ExecutionProfile:
    label: str
    start: datetime | None
    end: datetime | None
    event_count: int
    error_count: int
    services: dict[str, ServiceProfile]
    edges: dict[str, tuple[int, int]]  # "a->b" -> (calls, errors)

    @property
    def minutes(self) -> float:
        if self.start is None or self.end is None:
            return 0.0
        return max((self.end - self.start).total_seconds(), 1.0) / 60.0


def profile_events(label: str, events: Sequence[CanonicalEvent]) -> ExecutionProfile:
    ordered = sorted(events, key=lambda e: (e.timestamp, e.event_id))
    services: dict[str, ServiceProfile] = defaultdict(ServiceProfile)
    for event in ordered:
        profile = services[event.service]
        profile.events += 1
        profile.errors += int(event.is_error)
        if event.deployment_version:
            profile.versions.add(event.deployment_version)
        target = measured_service(event)
        if target is not None and event.duration_ms is not None:
            services[target].latencies.append(event.duration_ms)
    correlation = correlate(ordered)
    graph = build_graph(ordered, correlation)
    for name, node in graph.nodes.items():
        services[name].status = node.status
    return ExecutionProfile(
        label=label,
        start=ordered[0].timestamp if ordered else None,
        end=ordered[-1].timestamp if ordered else None,
        event_count=len(ordered),
        error_count=sum(1 for e in ordered if e.is_error),
        services=dict(services),
        edges={f"{e.source}->{e.target}": (e.call_count, e.error_count) for e in graph.edges},
    )


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _p95(values: list[float]) -> float | None:
    value = quantile(values, 0.95)
    return None if value is None else round(value, 1)


def compare_profiles(baseline: ExecutionProfile, target: ExecutionProfile) -> dict[str, Any]:
    reasons: list[str] = []
    warnings: list[str] = []
    for profile in (baseline, target):
        if profile.event_count < MIN_EVENTS:
            reasons.append(
                f"{profile.label} has only {profile.event_count} events (< {MIN_EVENTS})"
            )
        elif profile.minutes * 60 < MIN_SECONDS:
            reasons.append(f"{profile.label} covers less than {MIN_SECONDS:.0f} seconds")
    base_services, target_services = set(baseline.services), set(target.services)
    union = base_services | target_services
    overlap = len(base_services & target_services) / len(union) if union else 0.0
    if overlap < MIN_SERVICE_OVERLAP:
        reasons.append(
            f"service sets barely overlap (Jaccard {overlap:.2f} < {MIN_SERVICE_OVERLAP}); "
            "these look like different systems"
        )
    if baseline.minutes and target.minutes:
        ratio = max(baseline.minutes, target.minutes) / min(baseline.minutes, target.minutes)
        if ratio > 3:
            warnings.append(
                f"window lengths differ by {ratio:.1f}x; rates are normalised per minute"
            )
        base_volume = baseline.event_count / baseline.minutes
        target_volume = target.event_count / target.minutes
        if (
            base_volume
            and target_volume
            and max(base_volume, target_volume) / min(base_volume, target_volume) > 2
        ):
            warnings.append("traffic volume differs by more than 2x between the executions")

    rows: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for name in sorted(union):
        base = baseline.services.get(name)
        tgt = target.services.get(name)
        base_rate = _rate(base.errors, base.events) if base else None
        target_rate = _rate(tgt.errors, tgt.events) if tgt else None
        base_p95 = _p95(base.latencies) if base else None
        target_p95 = _p95(tgt.latencies) if tgt else None
        latency_note = None
        if base_p95 is None or target_p95 is None:
            latency_note = "not measured in " + (
                "either execution"
                if base_p95 is None and target_p95 is None
                else baseline.label
                if base_p95 is None
                else target.label
            )
        row: dict[str, Any] = {
            "service": name,
            "presence": "both" if base and tgt else ("baseline_only" if base else "target_only"),
            "baseline_events_per_min": round(base.events / baseline.minutes, 2)
            if base and baseline.minutes
            else None,
            "target_events_per_min": round(tgt.events / target.minutes, 2)
            if tgt and target.minutes
            else None,
            "baseline_error_rate": base_rate,
            "target_error_rate": target_rate,
            "error_rate_delta": round(target_rate - base_rate, 4)
            if base_rate is not None and target_rate is not None
            else None,
            "baseline_p95_ms": base_p95,
            "target_p95_ms": target_p95,
            "p95_ratio": round(target_p95 / base_p95, 2)
            if base_p95 and target_p95 is not None
            else None,
            "latency_note": latency_note,
            "baseline_versions": sorted(base.versions) if base else [],
            "target_versions": sorted(tgt.versions) if tgt else [],
            "baseline_status": base.status if base else None,
            "target_status": tgt.status if tgt else None,
        }
        rows.append(row)
        if row["presence"] != "both":
            findings.append(
                {
                    "kind": "service_presence",
                    "service": name,
                    "magnitude": 1.0,
                    "text": f"{name} appears only in the "
                    f"{'baseline' if row['presence'] == 'baseline_only' else 'target'} execution",
                }
            )
            continue
        delta = row["error_rate_delta"]
        if (
            delta is not None
            and abs(delta) >= 0.02
            and (tgt and tgt.errors + (base.errors if base else 0) >= 3)
        ):
            findings.append(
                {
                    "kind": "error_rate",
                    "service": name,
                    "magnitude": abs(delta),
                    "text": f"{name} error rate {base_rate:.1%} -> {target_rate:.1%}",
                }
            )
        ratio_value = row["p95_ratio"]
        if ratio_value is not None and (ratio_value >= 2 or ratio_value <= 0.5):
            findings.append(
                {
                    "kind": "latency",
                    "service": name,
                    "magnitude": min(abs(ratio_value - 1), 10.0) / 10,
                    "text": f"{name} p95 latency {base_p95:.0f} ms -> {target_p95:.0f} ms",
                }
            )
        if row["baseline_versions"] != row["target_versions"]:
            findings.append(
                {
                    "kind": "version",
                    "service": name,
                    "magnitude": 0.5,
                    "text": f"{name} versions {', '.join(row['baseline_versions']) or 'none'} -> "
                    f"{', '.join(row['target_versions']) or 'none'}",
                }
            )

    edge_rows: list[dict[str, Any]] = []
    for edge_id in sorted(set(baseline.edges) | set(target.edges)):
        base_calls, base_errors = baseline.edges.get(edge_id, (0, 0))
        target_calls, target_errors = target.edges.get(edge_id, (0, 0))
        presence = (
            "both"
            if edge_id in baseline.edges and edge_id in target.edges
            else "baseline_only"
            if edge_id in baseline.edges
            else "target_only"
        )
        edge_rows.append(
            {
                "id": edge_id,
                "presence": presence,
                "baseline_calls": base_calls,
                "target_calls": target_calls,
                "baseline_error_rate": _rate(base_errors, base_calls),
                "target_error_rate": _rate(target_errors, target_calls),
            }
        )
        if presence != "both":
            findings.append(
                {
                    "kind": "dependency",
                    "service": edge_id,
                    "magnitude": 0.6,
                    "text": f"dependency {edge_id} observed only in the "
                    f"{'baseline' if presence == 'baseline_only' else 'target'} execution",
                }
            )
        elif (
            target_errors >= 3
            and (_rate(target_errors, target_calls) or 0) - (_rate(base_errors, base_calls) or 0)
            >= 0.1
        ):
            findings.append(
                {
                    "kind": "dependency",
                    "service": edge_id,
                    "magnitude": (_rate(target_errors, target_calls) or 0),
                    "text": f"calls {edge_id} failing {_rate(base_errors, base_calls) or 0:.0%} -> "
                    f"{_rate(target_errors, target_calls) or 0:.0%}",
                }
            )

    findings.sort(key=lambda item: (-item["magnitude"], item["kind"], item["service"]))
    base_rate_total = _rate(baseline.error_count, baseline.event_count)
    target_rate_total = _rate(target.error_count, target.event_count)
    return {
        "comparable": not reasons,
        "incomparable_reasons": reasons,
        "warnings": warnings,
        "service_overlap": round(overlap, 3),
        "baseline": _profile_summary(baseline),
        "target": _profile_summary(target),
        "overall": {
            "baseline_error_rate": base_rate_total,
            "target_error_rate": target_rate_total,
            "error_rate_delta": round(target_rate_total - base_rate_total, 4)
            if base_rate_total is not None and target_rate_total is not None
            else None,
            "baseline_events_per_min": round(baseline.event_count / baseline.minutes, 2)
            if baseline.minutes
            else None,
            "target_events_per_min": round(target.event_count / target.minutes, 2)
            if target.minutes
            else None,
        },
        "services": rows,
        "edges": edge_rows,
        "findings": findings[:25],
    }


def _profile_summary(profile: ExecutionProfile) -> dict[str, Any]:
    return {
        "label": profile.label,
        "start": profile.start.isoformat() if profile.start else None,
        "end": profile.end.isoformat() if profile.end else None,
        "event_count": profile.event_count,
        "error_count": profile.error_count,
        "minutes": round(profile.minutes, 2),
        "service_count": len(profile.services),
    }
