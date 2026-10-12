"""Deterministic incident replay.

A replay is the ordered list of an incident window's events (sorted by timestamp, then
event ID) turned into frames. Each frame carries the *changes* to service health and the
call edge it exercised, so a client reconstructs the exact state at frame ``i`` by folding
frames ``0..i`` over ``initial_state``.

Service health is evaluated after every event from a sliding 30-second window of
simulated time over **all** events, independent of the display filter:

* ``failing``  - at least 3 errors and an error ratio of at least 20 %
* ``degraded`` - at least 1 error, or at least 3 warnings
* ``healthy``  - otherwise

Events hidden by a filter still advance the state; their changes are merged into the next
visible frame, so filtered and unfiltered replays agree on the state at every shown event.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from app.schemas.events import CanonicalEvent, EventType
from app.services.correlation import correlate
from app.services.graph_analysis import build_graph
from app.services.incidents import category

HEALTH_WINDOW = timedelta(seconds=30)
CALL_TYPES = (EventType.DEPENDENCY_CALL, EventType.TIMEOUT, EventType.RETRY)


class ReplayTooLargeError(ValueError):
    pass


@dataclass(frozen=True)
class ReplayFilter:
    services: tuple[str, ...] = ()
    severities: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()

    def matches(self, event: CanonicalEvent) -> bool:
        if self.services and event.service not in self.services:
            return False
        if self.severities and event.severity.value not in self.severities:
            return False
        return not (self.categories and category(event) not in self.categories)


class _Health:
    def __init__(self) -> None:
        self.window: deque[tuple[float, bool, bool]] = deque()
        self.total_errors = 0

    def add(self, seconds: float, is_error: bool, is_warning: bool) -> None:
        self.window.append((seconds, is_error, is_warning))
        self.total_errors += int(is_error)

    def status(self, now: float) -> str:
        horizon = now - HEALTH_WINDOW.total_seconds()
        while self.window and self.window[0][0] < horizon:
            self.window.popleft()
        errors = sum(1 for _, is_error, _ in self.window if is_error)
        warnings = sum(1 for _, _, is_warning in self.window if is_warning)
        if errors >= 3 and errors / len(self.window) >= 0.2:
            return "failing"
        if errors >= 1 or warnings >= 3:
            return "degraded"
        return "healthy"


def build_replay(
    incident_id: str,
    events: Sequence[CanonicalEvent],
    flt: ReplayFilter,
    *,
    max_frames: int = 5000,
) -> dict[str, Any]:
    ordered = sorted(events, key=lambda e: (e.timestamp, e.event_id))
    visible_count = sum(1 for event in ordered if flt.matches(event))
    if visible_count > max_frames:
        raise ReplayTooLargeError(
            f"replay would contain {visible_count} frames (limit {max_frames}); narrow the filters"
        )

    correlation = correlate(ordered)
    graph = build_graph(ordered, correlation)
    spans = {(e.trace_id, e.span_id): e for e in ordered if e.trace_id and e.span_id}
    services = sorted(graph.nodes)
    health = {name: _Health() for name in services}
    status = dict.fromkeys(services, "healthy")
    origin = ordered[0].timestamp if ordered else None

    frames: list[dict[str, Any]] = []
    pending: dict[str, str] = {}
    pending_errors: dict[str, int] = {}
    for event in ordered:
        assert origin is not None
        seconds = (event.timestamp - origin).total_seconds()
        owners = [event.service]
        edge: tuple[str, str] | None = None
        if event.target_service and event.event_type in CALL_TYPES:
            edge = (event.service, event.target_service)
            if event.event_type != EventType.RETRY:
                owners.append(event.target_service)
        elif event.trace_id and event.parent_span_id:
            parent = spans.get((event.trace_id, event.parent_span_id))
            if parent is not None and parent.service != event.service:
                edge = (parent.service, event.service)
        for owner in owners:
            if owner in health:
                health[owner].add(seconds, event.is_error, event.is_warning_or_worse)
                if event.is_error:
                    pending_errors[owner] = health[owner].total_errors
        for name in services:
            current = health[name].status(seconds)
            if current != status[name]:
                status[name] = current
                pending[name] = current

        if not flt.matches(event):
            continue
        frames.append(
            {
                "index": len(frames),
                "event_id": event.event_id,
                "timestamp": event.timestamp.isoformat(),
                "offset_ms": round(seconds * 1000, 3),
                "service": event.service,
                "target_service": event.target_service,
                "severity": event.severity.value,
                "category": category(event),
                "message": event.message[:240],
                "node_updates": dict(pending),
                "error_totals": dict(pending_errors),
                "edge": None
                if edge is None
                else {"id": f"{edge[0]}->{edge[1]}", "failed": event.is_error},
            }
        )
        pending = {}
        pending_errors = {}

    identity = json.dumps(
        {
            "incident": incident_id,
            "services": flt.services,
            "severities": flt.severities,
            "categories": flt.categories,
            "events": [event.event_id for event in ordered],
        },
        sort_keys=True,
    )
    return {
        "replay_id": "rpl_" + hashlib.sha256(identity.encode()).hexdigest()[:16],
        "incident_id": incident_id,
        "frame_count": len(frames),
        "total_events": len(ordered),
        "start": ordered[0].timestamp.isoformat() if ordered else None,
        "end": ordered[-1].timestamp.isoformat() if ordered else None,
        "filters": {
            "services": list(flt.services),
            "severities": list(flt.severities),
            "categories": list(flt.categories),
        },
        "nodes": [
            {"id": name, "kind": graph.nodes[name].kind, "depth": graph.nodes[name].depth}
            for name in services
        ],
        "edges": [
            {"id": f"{e.source}->{e.target}", "source": e.source, "target": e.target}
            for e in graph.edges
        ],
        "initial_state": dict.fromkeys(services, "healthy"),
        "health_rules": {
            "window_seconds": HEALTH_WINDOW.total_seconds(),
            "failing": "at least 3 errors and an error ratio of at least 20% in the window",
            "degraded": "at least 1 error or at least 3 warnings in the window",
        },
        "frames": frames,
    }
