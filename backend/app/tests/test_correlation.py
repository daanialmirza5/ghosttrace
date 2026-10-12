from __future__ import annotations

from app.services.correlation import correlate
from app.tests.factories import ev


def failing_chain():
    """gateway -> orders -> (dependency call) db; db call fails and errors bubble up."""
    return [
        ev(
            0.00,
            "gateway",
            "info",
            span_id="g1",
            trace_id="T",
            event_id="g-start",
            event_type="log",
        ),
        ev(
            0.10,
            "orders",
            "error",
            "dependency_call",
            trace_id="T",
            span_id="c1",
            parent_span_id="o1",
            target_service="db",
            error_type="PoolTimeout",
            event_id="dep-fail",
        ),
        ev(
            0.20,
            "orders",
            "error",
            trace_id="T",
            span_id="o1",
            parent_span_id="g1",
            event_id="orders-span",
        ),
        ev(0.30, "gateway", "error", trace_id="T", span_id="g1", event_id="gateway-span"),
    ]


def test_edges_from_trace_ancestry_and_dependency_calls() -> None:
    result = correlate(failing_chain())
    assert set(result.edges) == {("gateway", "orders"), ("orders", "db")}
    assert result.edges[("gateway", "orders")].sources == {"trace"}
    assert result.edges[("orders", "db")].sources == {"dependency_call"}
    assert result.edges[("orders", "db")].error_count == 1
    assert result.inferred_services == {"db"}
    assert result.observed_services == {"gateway", "orders"}


def test_error_propagation_and_trace_origin() -> None:
    result = correlate(failing_chain())
    pairs = {(p.from_service, p.to_service, p.basis) for p in result.propagations}
    assert ("db", "orders", "dependency_call") in pairs
    assert ("orders", "gateway", "trace_parent") in pairs
    trace = result.traces["T"]
    assert trace.origin_service == "db"
    assert trace.origin_event_id == "dep-fail"
    # gateway and orders errors are explained by failing children; the leaf is not.
    assert {"orders-span", "gateway-span"} <= result.explained_error_ids
    assert "dep-fail" not in result.explained_error_ids


def test_temporal_proximity_alone_creates_no_links() -> None:
    events = [
        ev(0.0, "orders", "error", event_type="log", event_id="a"),
        ev(0.0, "payments", "error", event_type="log", event_id="b"),
        ev(0.1, "gateway", "error", event_type="log", event_id="c"),
    ]
    result = correlate(events)
    assert result.edges == {}
    assert result.propagations == []
    assert result.related_event_ids("a") == []


def test_orphan_spans_are_counted() -> None:
    events = [
        ev(0, "a", span_id="s1", trace_id="T"),
        ev(1, "b", span_id="s2", parent_span_id="missing", trace_id="T"),
    ]
    result = correlate(events)
    assert result.orphan_span_count == 1
    assert result.traces["T"].orphan_span_ids == {"s2"}
    assert result.orphan_ratio == 0.5


def test_request_id_groups_without_trace() -> None:
    events = [
        ev(0, "a", request_id="r1", event_id="x"),
        ev(1, "b", request_id="r1", event_id="y"),
        ev(2, "c", request_id="r2", event_id="z"),
    ]
    result = correlate(events)
    assert result.related_event_ids("x") == ["y"]
    assert result.edges == {}


def test_same_service_parent_does_not_create_self_edge() -> None:
    events = [
        ev(0, "a", span_id="p", trace_id="T"),
        ev(1, "a", span_id="c", parent_span_id="p", trace_id="T"),
    ]
    assert correlate(events).edges == {}


def test_retry_events_count_as_retries_not_calls() -> None:
    events = [ev(i, "orders", "warning", "retry", target_service="inventory") for i in range(3)]
    edge = correlate(events).edges[("orders", "inventory")]
    assert edge.retry_count == 3
    assert edge.call_count == 0
