from __future__ import annotations

from app.services.correlation import correlate
from app.services.graph_analysis import build_graph
from app.tests.factories import ev


def call(seconds: float, source: str, target: str, severity: str = "info", **fields):
    return ev(
        seconds,
        source,
        severity,
        "dependency_call",
        target_service=target,
        duration_ms=fields.pop("duration_ms", 10.0),
        **fields,
    )


def test_cycles_are_detected_without_breaking_traversal() -> None:
    events = [call(0, "a", "b"), call(1, "b", "c"), call(2, "c", "a"), call(3, "c", "d")]
    graph = build_graph(events, correlate(events))
    assert graph.cycles == [["a", "b", "c"]]
    assert {e.source + e.target for e in graph.edges if e.in_cycle} == {"ab", "bc", "ca"}
    assert graph.reachable("a") == {"b", "c", "d"}
    assert graph.reachable("d", upstream=True) == {"a", "b", "c"}


def test_disconnected_components_and_entry_points() -> None:
    events = [call(0, "a", "b"), call(1, "x", "y"), ev(2, "lonely")]
    graph = build_graph(events, correlate(events))
    assert graph.components == 3
    assert graph.entry_points == ["a", "lonely", "x"]
    assert graph.nodes["b"].depth == 1


def test_inferred_node_status_from_failed_calls() -> None:
    events = [call(i, "api", "provider", "error", error_type="Timeout") for i in range(6)]
    events += [call(10 + i, "api", "provider") for i in range(4)]
    graph = build_graph(events, correlate(events))
    provider = graph.nodes["provider"]
    assert provider.kind == "inferred"
    assert provider.status == "failing"
    assert provider.latency_samples == 10
    edge = graph.edge("api", "provider")
    assert edge is not None and edge.error_rate == 0.6


def test_observed_node_statistics() -> None:
    events = [ev(i, "api", "error" if i < 3 else "info", duration_ms=float(i)) for i in range(20)]
    node = build_graph(events, correlate(events)).nodes["api"]
    assert node.error_count == 3
    assert node.status == "degraded"
    assert node.p50_ms == 9.5
    assert len(node.sample_error_event_ids) == 3


def test_empty_graph() -> None:
    graph = build_graph([], correlate([]))
    assert graph.nodes == {} and graph.edges == [] and graph.components == 0
