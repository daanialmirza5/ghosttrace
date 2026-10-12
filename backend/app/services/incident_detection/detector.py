"""Incident detection: turn raw events into observed signals, then group them.

Every signal is tagged ``observed`` (a direct count or measurement over imported events)
or ``inferred`` (a conclusion drawn from several observations, such as "this deployment
was followed by a regression"). Thresholds live in ``DetectionConfig`` and are documented
in docs/analysis.md.

Burst test: for a series of event times, counts are bucketed and a robust baseline rate is
estimated from the quietest 75% of buckets. A sliding window is flagged when its count is
both at least ``min_count`` and improbable under a Poisson model of the baseline
(p < ``p_threshold``). Flagged buckets are merged into intervals.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from app.schemas.events import CanonicalEvent, EventType, Severity
from app.services.correlation import CorrelationResult
from app.services.incident_detection.stats import (
    median,
    poisson_sf,
    quantile,
    trimmed_low_mean,
)

SignalType = Literal[
    "error_spike",
    "repeated_exception",
    "latency_increase",
    "timeout_cluster",
    "retry_storm",
    "dependency_failure",
    "deployment_regression",
    "missing_trace_context",
    "cascading_failure",
]
PRIMARY_SIGNALS: frozenset[str] = frozenset(
    {"error_spike", "latency_increase", "timeout_cluster", "retry_storm", "dependency_failure"}
)
CHANGE_TYPES = frozenset({EventType.DEPLOYMENT, EventType.CONFIG_CHANGE})
_TIMEOUT_PATTERN = re.compile("timeout|timed out", re.IGNORECASE)
_MAX_EVIDENCE = 25


@dataclass(frozen=True)
class DetectionConfig:
    window_seconds: float = 60.0
    min_bucket_seconds: float = 10.0
    max_bucket_seconds: float = 60.0
    target_buckets: int = 40
    p_threshold: float = 1e-4
    min_baseline_rate: float = 0.05
    # Baseline = mean of the quietest 75% of buckets (robust to incidents, not too low for
    # sparse series).
    baseline_keep_fraction: float = 0.75
    error_min_count: int = 6
    error_min_ratio: float = 0.1
    exception_min_count: int = 5
    timeout_min_count: int = 4
    retry_min_count: int = 8
    retry_min_ratio: float = 0.2
    dependency_min_failures: int = 4
    dependency_min_ratio: float = 0.25
    latency_min_samples: int = 5
    latency_ratio: float = 2.5
    latency_min_increase_ms: float = 250.0
    regression_window_seconds: float = 300.0
    regression_min_errors: int = 5
    regression_p_threshold: float = 1e-3
    orphan_ratio_threshold: float = 0.1
    change_lookback_seconds: float = 900.0


@dataclass
class Signal:
    id: str
    type: SignalType
    basis: Literal["observed", "inferred"]
    service: str
    start: datetime
    end: datetime
    count: int
    description: str
    evidence_event_ids: list[str]
    target_service: str | None = None
    metrics: dict[str, float | int | str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "type": self.type,
            "basis": self.basis,
            "service": self.service,
            "target_service": self.target_service,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "count": self.count,
            "description": self.description,
            "evidence_event_ids": self.evidence_event_ids,
            "metrics": self.metrics,
        }


@dataclass(frozen=True)
class ChangePoint:
    service: str
    at: datetime
    event_id: str
    kind: Literal["deployment", "config_change", "version_change"]
    description: str
    new_version: str | None = None
    previous_version: str | None = None


@dataclass
class IncidentDraft:
    start: datetime
    end: datetime
    signals: list[Signal]
    services: list[str]
    severity: Literal["critical", "major", "minor"]
    title: str
    error_count: int
    peak_error_ratio: float


@dataclass
class DetectionResult:
    incidents: list[IncidentDraft]
    data_quality: list[Signal]
    all_signals: list[Signal]
    bucket_seconds: float
    change_points: list[ChangePoint]


@dataclass
class _Interval:
    start: float
    end: float
    ids: list[str]
    count: int
    denominator: int = 0


class _Clock:
    def __init__(self, events: Sequence[CanonicalEvent], config: DetectionConfig) -> None:
        self.t0 = events[0].timestamp
        span = max(1.0, (events[-1].timestamp - self.t0).total_seconds())
        raw = span / config.target_buckets
        self.bucket = float(min(config.max_bucket_seconds, max(config.min_bucket_seconds, raw)))
        self.n_buckets = int(span // self.bucket) + 1
        self.window = max(1, math.ceil(config.window_seconds / self.bucket))

    def seconds(self, moment: datetime) -> float:
        return (moment - self.t0).total_seconds()

    def at(self, seconds: float) -> datetime:
        return self.t0 + timedelta(seconds=seconds)

    def bucket_of(self, seconds: float) -> int:
        return min(self.n_buckets - 1, max(0, int(seconds // self.bucket)))


def _bursts(
    items: Sequence[tuple[float, str]],
    clock: _Clock,
    config: DetectionConfig,
    *,
    min_count: int,
    denominators: Sequence[int] | None = None,
    min_ratio: float = 0.0,
) -> list[_Interval]:
    if len(items) < min_count:
        return []
    counts = [0] * clock.n_buckets
    for seconds, _ in items:
        counts[clock.bucket_of(seconds)] += 1
    baseline = max(
        trimmed_low_mean(counts, config.baseline_keep_fraction), config.min_baseline_rate
    )
    expected = baseline * clock.window
    hot = [False] * clock.n_buckets
    for start in range(max(1, clock.n_buckets - clock.window + 1)):
        stop = min(clock.n_buckets, start + clock.window)
        k = sum(counts[start:stop])
        if k < min_count or poisson_sf(k, expected) >= config.p_threshold:
            continue
        if denominators is not None:
            total = sum(denominators[start:stop])
            if total == 0 or k / total < min_ratio:
                continue
        for index in range(start, stop):
            if counts[index] > baseline:
                hot[index] = True

    intervals: list[tuple[int, int]] = []
    for index, flag in enumerate(hot):
        if not flag:
            continue
        if intervals and index - intervals[-1][1] <= 2:
            intervals[-1] = (intervals[-1][0], index)
        else:
            intervals.append((index, index))

    result: list[_Interval] = []
    for first, last in intervals:
        lo, hi = first * clock.bucket, (last + 1) * clock.bucket
        inside = [(seconds, event_id) for seconds, event_id in items if lo <= seconds < hi]
        if len(inside) < min_count:
            continue
        denominator = sum(denominators[first : last + 1]) if denominators is not None else 0
        result.append(
            _Interval(
                start=inside[0][0],
                end=inside[-1][0],
                ids=[event_id for _, event_id in inside],
                count=len(inside),
                denominator=denominator,
            )
        )
    return result


def _series(
    events: Sequence[CanonicalEvent],
    clock: _Clock,
    key: Callable[[CanonicalEvent], str | tuple[str, str] | None],
) -> dict[str | tuple[str, str], list[tuple[float, str]]]:
    grouped: dict[str | tuple[str, str], list[tuple[float, str]]] = defaultdict(list)
    for event in events:
        group = key(event)
        if group is not None:
            grouped[group].append((clock.seconds(event.timestamp), event.event_id))
    return grouped


def _bucket_totals(
    events: Sequence[CanonicalEvent],
    clock: _Clock,
    key: Callable[[CanonicalEvent], str | tuple[str, str] | None],
) -> dict[str | tuple[str, str], list[int]]:
    totals: dict[str | tuple[str, str], list[int]] = defaultdict(lambda: [0] * clock.n_buckets)
    for event in events:
        group = key(event)
        if group is not None:
            totals[group][clock.bucket_of(clock.seconds(event.timestamp))] += 1
    return totals


def is_timeout(event: CanonicalEvent) -> bool:
    if event.event_type == EventType.TIMEOUT:
        return True
    return bool(event.error_type and _TIMEOUT_PATTERN.search(event.error_type))


def measured_service(event: CanonicalEvent) -> str | None:
    """Which service a latency sample describes: the callee for outbound calls."""
    if event.duration_ms is None:
        return None
    if event.event_type in (EventType.DEPENDENCY_CALL, EventType.TIMEOUT):
        return event.target_service
    if event.event_type in (EventType.SPAN, EventType.REQUEST):
        return event.service
    return None


def find_change_points(events: Sequence[CanonicalEvent]) -> list[ChangePoint]:
    """Explicit deployment/config events plus implicit version flips without one."""
    points: list[ChangePoint] = []
    for event in events:
        if event.event_type in CHANGE_TYPES:
            previous = event.attributes.get("previous_version")
            points.append(
                ChangePoint(
                    service=event.service,
                    at=event.timestamp,
                    event_id=event.event_id,
                    kind="deployment"
                    if event.event_type == EventType.DEPLOYMENT
                    else "config_change",
                    description=event.message,
                    new_version=event.deployment_version,
                    previous_version=str(previous) if previous is not None else None,
                )
            )
    explicit = {(point.service, point.new_version) for point in points}
    last_version: dict[str, str] = {}
    for event in events:
        version = event.deployment_version
        if version is None:
            continue
        previous = last_version.get(event.service)
        last_version[event.service] = version
        if previous is None or previous == version:
            continue
        if (event.service, version) in explicit:
            continue
        explicit.add((event.service, version))
        points.append(
            ChangePoint(
                service=event.service,
                at=event.timestamp,
                event_id=event.event_id,
                kind="version_change",
                description=f"first event reporting {event.service} version {version} "
                f"(previously {previous}); no deployment event was imported",
                new_version=version,
                previous_version=previous,
            )
        )
    points.sort(key=lambda point: (point.at, point.event_id))
    return points


def detect_incidents(
    events: Sequence[CanonicalEvent],
    correlation: CorrelationResult,
    config: DetectionConfig | None = None,
) -> DetectionResult:
    config = config or DetectionConfig()
    if not events:
        return DetectionResult([], [], [], config.min_bucket_seconds, [])
    clock = _Clock(events, config)
    raw: list[tuple[str, Signal]] = []

    def add(signal: Signal) -> None:
        raw.append((signal.type, signal))

    def make(
        kind: SignalType,
        basis: Literal["observed", "inferred"],
        service: str,
        interval: _Interval,
        description: str,
        *,
        target: str | None = None,
        metrics: dict[str, float | int | str] | None = None,
    ) -> Signal:
        return Signal(
            id="",
            type=kind,
            basis=basis,
            service=service,
            target_service=target,
            start=clock.at(interval.start),
            end=clock.at(interval.end),
            count=interval.count,
            description=description,
            evidence_event_ids=interval.ids[:_MAX_EVIDENCE],
            metrics=metrics or {},
        )

    totals_by_service = _bucket_totals(events, clock, lambda e: e.service)

    # Error spikes per service.
    errors = _series(events, clock, lambda e: e.service if e.is_error else None)
    for service, items in errors.items():
        assert isinstance(service, str)
        for interval in _bursts(
            items,
            clock,
            config,
            min_count=config.error_min_count,
            denominators=totals_by_service[service],
            min_ratio=config.error_min_ratio,
        ):
            ratio = interval.count / max(1, interval.denominator)
            add(
                make(
                    "error_spike",
                    "observed",
                    service,
                    interval,
                    f"{interval.count} error events in {service} "
                    f"({ratio:.0%} of its events in the interval)",
                    metrics={"error_ratio": round(ratio, 3), "events": interval.denominator},
                )
            )

    # Repeated exceptions per (service, error_type).
    exceptions = _series(
        events,
        clock,
        lambda e: (e.service, e.error_type) if e.is_error and e.error_type else None,
    )
    for group, items in exceptions.items():
        assert isinstance(group, tuple)
        service, error_type = group
        for interval in _bursts(items, clock, config, min_count=config.exception_min_count):
            add(
                make(
                    "repeated_exception",
                    "observed",
                    service,
                    interval,
                    f"{error_type} raised {interval.count} times in {service}",
                    metrics={"error_type": error_type},
                )
            )

    # Timeouts per (service, target).
    timeouts = _series(
        events,
        clock,
        lambda e: (e.service, e.target_service or "") if is_timeout(e) and e.is_error else None,
    )
    for group, items in timeouts.items():
        assert isinstance(group, tuple)
        service, target = group
        for interval in _bursts(items, clock, config, min_count=config.timeout_min_count):
            where = f" calling {target}" if target else ""
            add(
                make(
                    "timeout_cluster",
                    "observed",
                    service,
                    interval,
                    f"{interval.count} timeouts in {service}{where}",
                    target=target or None,
                )
            )

    # Client-side calls per (service, target), used as failure-ratio denominators.
    calls_by_edge = _bucket_totals(
        events,
        clock,
        lambda e: (
            (e.service, e.target_service)
            if e.target_service and e.event_type in (EventType.DEPENDENCY_CALL, EventType.TIMEOUT)
            else None
        ),
    )

    # Retry storms per (service, target), relative to all calls toward that target.
    retries = _series(
        events,
        clock,
        lambda e: (e.service, e.target_service or "") if e.event_type == EventType.RETRY else None,
    )
    retry_denominators = _retry_denominators(events, clock)
    for group, items in retries.items():
        assert isinstance(group, tuple)
        service, target = group
        denominators = retry_denominators.get(group)
        for interval in _bursts(
            items,
            clock,
            config,
            min_count=config.retry_min_count,
            denominators=denominators,
            min_ratio=config.retry_min_ratio,
        ):
            attempts = [
                correlation.events_by_id[event_id].attributes.get("retry_attempt")
                for event_id in interval.ids
            ]
            max_attempt = max((int(a) for a in attempts if isinstance(a, int | float)), default=0)
            where = f" toward {target}" if target else ""
            add(
                make(
                    "retry_storm",
                    "observed",
                    service,
                    interval,
                    f"{interval.count} retries from {service}{where}"
                    + (f" (up to attempt {max_attempt})" if max_attempt else ""),
                    target=target or None,
                    metrics={"max_attempt": max_attempt},
                )
            )

    # Dependency failures per observed edge.
    failed_calls = _series(
        events,
        clock,
        lambda e: (
            (e.service, e.target_service)
            if e.target_service
            and e.is_error
            and e.event_type in (EventType.DEPENDENCY_CALL, EventType.TIMEOUT)
            else None
        ),
    )
    for group, items in failed_calls.items():
        assert isinstance(group, tuple)
        service, target = group
        for interval in _bursts(
            items,
            clock,
            config,
            min_count=config.dependency_min_failures,
            denominators=calls_by_edge.get(group),
            min_ratio=config.dependency_min_ratio,
        ):
            ratio = interval.count / max(1, interval.denominator)
            add(
                make(
                    "dependency_failure",
                    "observed",
                    service,
                    interval,
                    f"{interval.count} failed calls from {service} to {target} "
                    f"({ratio:.0%} of calls)",
                    target=target,
                    metrics={"failure_ratio": round(ratio, 3)},
                )
            )

    for signal in _latency_signals(events, clock, config):
        add(signal)

    change_points = find_change_points(events)
    for signal in _regressions(events, change_points, clock, config):
        add(signal)

    signals = sorted(
        (signal for _, signal in raw),
        key=lambda s: (s.start, s.type, s.service, s.target_service or ""),
    )
    for index, signal in enumerate(signals, start=1):
        signal.id = f"sig-{index:03d}"

    data_quality = _data_quality(correlation, events, config, clock)
    incidents = _group(signals, events, correlation, clock, config)
    return DetectionResult(
        incidents=incidents,
        data_quality=data_quality,
        all_signals=signals,
        bucket_seconds=clock.bucket,
        change_points=change_points,
    )


def _retry_denominators(
    events: Sequence[CanonicalEvent], clock: _Clock
) -> dict[tuple[str, str], list[int]]:
    """Calls from service to target, counting both client calls and child spans."""
    totals: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0] * clock.n_buckets)
    spans: dict[tuple[str, str], CanonicalEvent] = {}
    for event in events:
        if event.trace_id and event.span_id:
            spans.setdefault((event.trace_id, event.span_id), event)
    for event in events:
        bucket = clock.bucket_of(clock.seconds(event.timestamp))
        if event.event_type == EventType.RETRY and event.target_service:
            totals[(event.service, event.target_service)][bucket] += 1
        elif event.trace_id and event.parent_span_id:
            parent = spans.get((event.trace_id, event.parent_span_id))
            first_of_span = (
                event.span_id is not None and spans.get((event.trace_id, event.span_id)) is event
            )
            if parent is not None and parent.service != event.service and first_of_span:
                totals[(parent.service, event.service)][bucket] += 1
        elif event.target_service and event.event_type in (
            EventType.DEPENDENCY_CALL,
            EventType.TIMEOUT,
        ):
            totals[(event.service, event.target_service)][bucket] += 1
    return dict(totals)


def _latency_signals(
    events: Sequence[CanonicalEvent], clock: _Clock, config: DetectionConfig
) -> list[Signal]:
    samples: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
    for event in events:
        service = measured_service(event)
        if service is not None and event.duration_ms is not None:
            samples[service].append(
                (clock.seconds(event.timestamp), event.duration_ms, event.event_id)
            )
    signals: list[Signal] = []
    for service, items in samples.items():
        if len(items) < config.latency_min_samples * 3:
            continue
        windows: list[tuple[int, float, float]] = []
        by_bucket: dict[int, list[float]] = defaultdict(list)
        for seconds, duration, _ in items:
            by_bucket[clock.bucket_of(seconds)].append(duration)
        for start in range(max(1, clock.n_buckets - clock.window + 1)):
            values = [v for b in range(start, start + clock.window) for v in by_bucket.get(b, ())]
            if len(values) >= config.latency_min_samples:
                p50 = quantile(values, 0.5)
                p90 = quantile(values, 0.9)
                assert p50 is not None and p90 is not None
                windows.append((start, p50, p90))
        if len(windows) < 3:
            continue
        base_p50 = median([w[1] for w in windows]) or 0.0
        base_p90 = median([w[2] for w in windows]) or 0.0
        hot: set[int] = set()
        for start, p50, p90 in windows:
            p90_hot = p90 >= max(
                base_p90 * config.latency_ratio, base_p90 + config.latency_min_increase_ms
            )
            p50_hot = p50 >= max(
                base_p50 * config.latency_ratio, base_p50 + config.latency_min_increase_ms
            )
            if p90_hot or p50_hot:
                hot.update(range(start, start + clock.window))
        if not hot:
            continue
        threshold = max(base_p90 * config.latency_ratio, base_p90 + config.latency_min_increase_ms)
        for first, last in _merge_buckets(sorted(hot)):
            lo, hi = first * clock.bucket, (last + 1) * clock.bucket
            slow = [
                (seconds, duration, event_id)
                for seconds, duration, event_id in items
                if lo <= seconds < hi and duration >= threshold * 0.8
            ]
            if len(slow) < config.latency_min_samples:
                continue
            inside = [d for s, d, _ in items if lo <= s < hi]
            p90_inside = quantile(inside, 0.9) or 0.0
            interval = _Interval(
                start=slow[0][0], end=slow[-1][0], ids=[e for _, _, e in slow], count=len(slow)
            )
            signals.append(
                Signal(
                    id="",
                    type="latency_increase",
                    basis="observed",
                    service=service,
                    start=clock.at(interval.start),
                    end=clock.at(interval.end),
                    count=interval.count,
                    description=f"{service} p90 latency {p90_inside:.0f} ms vs baseline "
                    f"{base_p90:.0f} ms ({len(slow)} slow samples)",
                    evidence_event_ids=interval.ids[:_MAX_EVIDENCE],
                    metrics={
                        "baseline_p90_ms": round(base_p90, 1),
                        "window_p90_ms": round(p90_inside, 1),
                        "baseline_p50_ms": round(base_p50, 1),
                    },
                )
            )
    return signals


def _merge_buckets(indices: list[int]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for index in indices:
        if merged and index - merged[-1][1] <= 2:
            merged[-1] = (merged[-1][0], index)
        else:
            merged.append((index, index))
    return merged


def _regressions(
    events: Sequence[CanonicalEvent],
    change_points: Sequence[ChangePoint],
    clock: _Clock,
    config: DetectionConfig,
) -> list[Signal]:
    signals: list[Signal] = []
    window = timedelta(seconds=config.regression_window_seconds)
    for point in change_points:
        before_start = max(events[0].timestamp, point.at - window)
        after_end = min(events[-1].timestamp, point.at + window)
        before_seconds = (point.at - before_start).total_seconds()
        after_seconds = (after_end - point.at).total_seconds()
        if after_seconds < 30:
            continue
        own = [e for e in events if e.service == point.service]
        before = [e for e in own if before_start <= e.timestamp < point.at and e.is_error]
        after = [e for e in own if point.at <= e.timestamp <= after_end and e.is_error]
        rate_before = (len(before) + 0.5) / max(before_seconds, 60.0)
        expected = rate_before * after_seconds
        if len(after) < config.regression_min_errors:
            continue
        if poisson_sf(len(after), expected) >= config.regression_p_threshold:
            continue
        version = f" {point.new_version}" if point.new_version else ""
        signals.append(
            Signal(
                id="",
                type="deployment_regression",
                basis="inferred",
                service=point.service,
                start=point.at,
                end=after[-1].timestamp,
                count=len(after),
                description=f"{point.kind.replace('_', ' ')} of {point.service}{version} was "
                f"followed by {len(after)} errors in {after_seconds / 60:.0f} min "
                f"(vs {len(before)} in the preceding {before_seconds / 60:.0f} min)",
                evidence_event_ids=[
                    point.event_id,
                    *[e.event_id for e in after[: _MAX_EVIDENCE - 1]],
                ],
                metrics={
                    "change_event_id": point.event_id,
                    "errors_before": len(before),
                    "errors_after": len(after),
                    "change_kind": point.kind,
                },
            )
        )
    return signals


def _data_quality(
    correlation: CorrelationResult,
    events: Sequence[CanonicalEvent],
    config: DetectionConfig,
    clock: _Clock,
) -> list[Signal]:
    signals: list[Signal] = []
    if correlation.span_count >= 50 and correlation.orphan_ratio >= config.orphan_ratio_threshold:
        orphan_events = [
            e
            for e in events
            if e.trace_id
            and e.span_id
            and e.span_id in correlation.traces[e.trace_id].orphan_span_ids
        ]
        signals.append(
            Signal(
                id="dq-orphan-spans",
                type="missing_trace_context",
                basis="observed",
                service="*",
                start=orphan_events[0].timestamp if orphan_events else events[0].timestamp,
                end=orphan_events[-1].timestamp if orphan_events else events[-1].timestamp,
                count=correlation.orphan_span_count,
                description=f"{correlation.orphan_ratio:.0%} of spans reference a parent span "
                "that is not in the import; trace ancestry is incomplete",
                evidence_event_ids=[e.event_id for e in orphan_events[:_MAX_EVIDENCE]],
                metrics={"orphan_ratio": round(correlation.orphan_ratio, 3)},
            )
        )
    traced_ratio = correlation.traced_event_count / len(events)
    if traced_ratio < 0.2:
        signals.append(
            Signal(
                id="dq-no-tracing",
                type="missing_trace_context",
                basis="observed",
                service="*",
                start=events[0].timestamp,
                end=events[-1].timestamp,
                count=len(events) - correlation.traced_event_count,
                description=f"only {traced_ratio:.0%} of events carry a trace ID; causal links "
                "between services cannot be reconstructed from traces",
                evidence_event_ids=[],
                metrics={"traced_ratio": round(traced_ratio, 3)},
            )
        )
    return signals


def _group(
    signals: list[Signal],
    events: Sequence[CanonicalEvent],
    correlation: CorrelationResult,
    clock: _Clock,
    config: DetectionConfig,
) -> list[IncidentDraft]:
    primary = [s for s in signals if s.type in PRIMARY_SIGNALS]
    gap = timedelta(seconds=max(60.0, 2 * clock.bucket))
    clusters: list[list[Signal]] = []
    for signal in primary:
        if clusters and signal.start <= max(s.end for s in clusters[-1]) + gap:
            clusters[-1].append(signal)
        else:
            clusters.append([signal])

    drafts: list[IncidentDraft] = []
    lookback = timedelta(seconds=config.change_lookback_seconds)
    for cluster in clusters:
        start = min(s.start for s in cluster)
        end = max(s.end for s in cluster)
        attached = list(cluster)
        for signal in signals:
            if signal in attached or signal.type in PRIMARY_SIGNALS:
                continue
            if signal.type == "deployment_regression":
                if start - lookback <= signal.start <= end:
                    attached.append(signal)
            elif signal.start <= end + gap and signal.end >= start - gap:
                attached.append(signal)

        window_events = [e for e in events if start - gap <= e.timestamp <= end + gap]
        error_events = [e for e in window_events if e.is_error]
        cascade = _cascade(attached, correlation, error_events)
        if cascade is not None:
            attached.append(cascade)
        attached.sort(key=lambda s: (s.start, s.id))

        services = sorted(
            {s.service for s in attached if s.service != "*"}
            | {s.target_service for s in attached if s.target_service}
        )
        peak_ratio = max(
            (float(s.metrics.get("error_ratio", 0.0)) for s in attached if s.type == "error_spike"),
            default=0.0,
        )
        severity: Literal["critical", "major", "minor"]
        if peak_ratio >= 0.3 or len(error_events) >= 100:
            severity = "critical"
        elif (
            peak_ratio >= 0.1
            or len(error_events) >= 30
            or any(s.type == "latency_increase" for s in attached)
        ):
            severity = "major"
        else:
            severity = "minor"
        drafts.append(
            IncidentDraft(
                start=start,
                end=end,
                signals=attached,
                services=services,
                severity=severity,
                title=_title(attached, services),
                error_count=len(error_events),
                peak_error_ratio=round(peak_ratio, 3),
            )
        )
    return drafts


def _cascade(
    signals: list[Signal], correlation: CorrelationResult, error_events: list[CanonicalEvent]
) -> Signal | None:
    """Inferred: errors in several services connected by observed propagation links."""
    failing = {s.service for s in signals if s.type in ("error_spike", "dependency_failure")}
    failing |= {
        s.target_service for s in signals if s.type == "dependency_failure" and s.target_service
    }
    if len(failing) < 2:
        return None
    window_ids = {e.event_id for e in error_events}
    links: Counter[tuple[str, str]] = Counter()
    evidence: list[str] = []
    for propagation in correlation.propagations:
        if propagation.to_event_id not in window_ids:
            continue
        if propagation.from_service in failing and propagation.to_service in failing:
            links[(propagation.from_service, propagation.to_service)] += 1
            if len(evidence) < _MAX_EVIDENCE:
                evidence.append(propagation.to_event_id)
    strong = {link for link, count in links.items() if count >= 3}
    if not strong:
        return None
    chain = _longest_chain(strong)
    first = min((correlation.events_by_id[eid] for eid in evidence), key=lambda e: e.timestamp)
    last = max((correlation.events_by_id[eid] for eid in evidence), key=lambda e: e.timestamp)
    return Signal(
        id=f"{signals[0].id}-cascade",
        type="cascading_failure",
        basis="inferred",
        service=chain[0],
        start=first.timestamp,
        end=last.timestamp,
        count=sum(links[link] for link in strong),
        description="errors propagated along observed calls: " + " -> ".join(chain),
        evidence_event_ids=evidence,
        metrics={"chain": " -> ".join(chain)},
    )


def _longest_chain(links: set[tuple[str, str]]) -> list[str]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for source, target in sorted(links):
        adjacency[source].append(target)
    best: list[str] = []

    def walk(node: str, path: list[str]) -> None:
        nonlocal best
        if len(path) > len(best):
            best = list(path)
        for nxt in adjacency.get(node, ()):
            if nxt not in path:
                walk(nxt, [*path, nxt])

    for source in sorted(adjacency):
        walk(source, [source])
    return best


_TITLES: dict[str, str] = {
    "retry_storm": "Retry storm",
    "dependency_failure": "Dependency failures",
    "timeout_cluster": "Timeouts",
    "error_spike": "Error spike",
    "latency_increase": "Latency increase",
}


def _title(signals: list[Signal], services: list[str]) -> str:
    """Name the two primary symptom types with the most supporting events."""
    volume: Counter[str] = Counter()
    for signal in signals:
        if signal.type in _TITLES:
            volume[signal.type] += signal.count
    parts = [_TITLES[key] for key, _ in sorted(volume.items(), key=lambda kv: (-kv[1], kv[0]))]
    parts = parts[:2]
    head = parts[0] if parts else "Anomaly"
    if len(parts) == 2:
        head = parts[0] + " and " + parts[1].lower()
    return f"{head} affecting {len(services)} service{'s' if len(services) != 1 else ''}"


def severity_at_least(event: CanonicalEvent, level: Severity) -> bool:
    order = list(Severity)
    return order.index(event.severity) >= order.index(level)
