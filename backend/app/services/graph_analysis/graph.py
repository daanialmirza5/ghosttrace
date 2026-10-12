"""Directed service dependency graph built only from observed call evidence.

Nodes are services that emitted events (``observed``) or that only appear as the target of
calls (``inferred``). Edges come from the correlation engine (trace ancestry and explicit
``target_service`` calls). Cycles are detected with Tarjan's algorithm and reported rather
than breaking traversal; reachability uses an explicit stack, so cyclic or disconnected
graphs are safe.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.schemas.events import CanonicalEvent
from app.services.correlation import CorrelationResult
from app.services.incident_detection.detector import measured_service
from app.services.incident_detection.stats import quantile

NodeStatus = Literal["healthy", "degraded", "failing", "unknown"]


@dataclass
class ServiceNode:
    name: str
    kind: Literal["observed", "inferred"]
    event_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    latency_samples: int = 0
    p50_ms: float | None = None
    p95_ms: float | None = None
    versions: list[str] = field(default_factory=list)
    first_error_at: datetime | None = None
    sample_error_event_ids: list[str] = field(default_factory=list)
    status: NodeStatus = "unknown"
    depth: int | None = None

    @property
    def error_rate(self) -> float | None:
        return self.error_count / self.event_count if self.event_count else None


@dataclass
class ServiceEdge:
    source: str
    target: str
    call_count: int
    error_count: int
    retry_count: int
    p50_ms: float | None
    p95_ms: float | None
    evidence_types: list[str]
    evidence_event_ids: list[str]
    first_error_event_id: str | None
    in_cycle: bool = False

    @property
    def error_rate(self) -> float | None:
        return self.error_count / self.call_count if self.call_count else None


@dataclass
class ServiceGraph:
    nodes: dict[str, ServiceNode]
    edges: list[ServiceEdge]
    cycles: list[list[str]]
    components: int
    entry_points: list[str]

    def _adjacency(self, reverse: bool = False) -> dict[str, list[str]]:
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in self.edges:
            if reverse:
                adjacency[edge.target].append(edge.source)
            else:
                adjacency[edge.source].append(edge.target)
        return adjacency

    def reachable(self, start: str, *, upstream: bool = False) -> set[str]:
        """Services reachable from ``start`` (callees), or that reach it when ``upstream``."""
        adjacency = self._adjacency(reverse=upstream)
        seen: set[str] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            for nxt in adjacency.get(node, ()):
                if nxt not in seen and nxt != start:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    def edge(self, source: str, target: str) -> ServiceEdge | None:
        return next((e for e in self.edges if e.source == source and e.target == target), None)


def _status(node: ServiceNode, incoming: Sequence[ServiceEdge]) -> NodeStatus:
    if node.kind == "inferred":
        calls = sum(edge.call_count for edge in incoming)
        failures = sum(edge.error_count for edge in incoming)
        if calls == 0:
            return "unknown"
        rate = failures / calls
    else:
        if node.event_count == 0:
            return "unknown"
        rate = node.error_count / node.event_count
        failures = node.error_count
    if rate >= 0.2 and failures >= 5:
        return "failing"
    if (rate >= 0.05 and failures >= 3) or (failures >= 1 and rate >= 0.2):
        return "degraded"
    return "healthy"


def _tarjan(nodes: Iterable[str], adjacency: dict[str, list[str]]) -> list[list[str]]:
    index = 0
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []

    for root in sorted(nodes):
        if root in indices:
            continue
        # Iterative DFS to avoid recursion limits on large graphs.
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, child_index = work.pop()
            if child_index == 0:
                indices[node] = lowlink[node] = index
                index += 1
                stack.append(node)
                on_stack.add(node)
            children = sorted(adjacency.get(node, ()))
            if child_index < len(children):
                work.append((node, child_index + 1))
                child = children[child_index]
                if child not in indices:
                    work.append((child, 0))
                elif child in on_stack:
                    lowlink[node] = min(lowlink[node], indices[child])
                continue
            if lowlink[node] == indices[node]:
                component: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(sorted(component))
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])
    return components


def build_graph(events: Sequence[CanonicalEvent], correlation: CorrelationResult) -> ServiceGraph:
    nodes: dict[str, ServiceNode] = {}
    latencies: dict[str, list[float]] = defaultdict(list)
    versions: dict[str, set[str]] = defaultdict(set)

    for event in events:
        node = nodes.setdefault(event.service, ServiceNode(name=event.service, kind="observed"))
        node.event_count += 1
        if event.is_error:
            node.error_count += 1
            if node.first_error_at is None:
                node.first_error_at = event.timestamp
            if len(node.sample_error_event_ids) < 10:
                node.sample_error_event_ids.append(event.event_id)
        elif event.is_warning_or_worse:
            node.warning_count += 1
        if event.deployment_version:
            versions[event.service].add(event.deployment_version)
        measured = measured_service(event)
        if measured is not None and event.duration_ms is not None:
            latencies[measured].append(event.duration_ms)

    for service in correlation.inferred_services:
        nodes.setdefault(service, ServiceNode(name=service, kind="inferred"))

    edges: list[ServiceEdge] = []
    for (source, target), evidence in sorted(correlation.edges.items()):
        nodes.setdefault(source, ServiceNode(name=source, kind="inferred"))
        nodes.setdefault(target, ServiceNode(name=target, kind="inferred"))
        edges.append(
            ServiceEdge(
                source=source,
                target=target,
                call_count=evidence.call_count,
                error_count=evidence.error_count,
                retry_count=evidence.retry_count,
                p50_ms=_round(quantile(evidence.durations_ms, 0.5)),
                p95_ms=_round(quantile(evidence.durations_ms, 0.95)),
                evidence_types=sorted(evidence.sources),
                evidence_event_ids=list(evidence.evidence_event_ids),
                first_error_event_id=evidence.first_error_event_id,
            )
        )

    incoming: dict[str, list[ServiceEdge]] = defaultdict(list)
    for edge in edges:
        incoming[edge.target].append(edge)
    for name, node in nodes.items():
        samples = latencies.get(name, [])
        node.latency_samples = len(samples)
        node.p50_ms = _round(quantile(samples, 0.5))
        node.p95_ms = _round(quantile(samples, 0.95))
        node.versions = sorted(versions.get(name, set()))
        node.status = _status(node, incoming.get(name, []))

    adjacency: dict[str, list[str]] = defaultdict(list)
    undirected: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adjacency[edge.source].append(edge.target)
        undirected[edge.source].add(edge.target)
        undirected[edge.target].add(edge.source)
    cycles = [c for c in _tarjan(nodes, adjacency) if len(c) > 1]
    cyclic = {member for cycle in cycles for member in cycle}
    for edge in edges:
        edge.in_cycle = edge.source in cyclic and edge.target in cyclic

    entry_points = sorted(name for name in nodes if not incoming.get(name))
    # Breadth-first depth from entry points; nodes only reachable through cycles keep None.
    queue: deque[str] = deque(entry_points)
    for name in entry_points:
        nodes[name].depth = 0
    while queue:
        current = queue.popleft()
        for nxt in sorted(adjacency.get(current, ())):
            if nodes[nxt].depth is None:
                nodes[nxt].depth = (nodes[current].depth or 0) + 1
                queue.append(nxt)

    components = 0
    seen: set[str] = set()
    for name in sorted(nodes):
        if name in seen:
            continue
        components += 1
        stack = [name]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(undirected.get(current, ()))

    return ServiceGraph(
        nodes=nodes,
        edges=edges,
        cycles=cycles,
        components=components,
        entry_points=entry_points,
    )


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)
