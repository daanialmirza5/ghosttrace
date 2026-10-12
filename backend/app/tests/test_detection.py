from __future__ import annotations

import pytest

from app.services.correlation import correlate
from app.services.incident_detection import detect_incidents, find_change_points
from app.services.incident_detection.stats import poisson_sf, quantile, trimmed_low_mean
from app.tests.factories import ev, scenario_events


def test_poisson_sf() -> None:
    assert poisson_sf(0, 3.0) == 1.0
    assert poisson_sf(1, 0.0) == 0.0
    assert poisson_sf(1, 1.0) == pytest.approx(1 - 0.36787944, rel=1e-6)
    assert poisson_sf(10, 1.0) < 1e-6


def test_quantile_and_trimmed_mean() -> None:
    assert quantile([], 0.5) is None
    assert quantile([1, 2, 3, 4], 0.5) == 2.5
    assert trimmed_low_mean([0, 0, 0, 100], keep=0.75) == 0


def steady_traffic(seconds: int, service: str = "api", every: float = 2.0):
    return [ev(t * every, service, duration_ms=20.0) for t in range(int(seconds / every))]


def test_error_spike_detected_against_quiet_baseline() -> None:
    events = steady_traffic(600)
    events += [ev(300 + i, "api", "error", error_type="Boom") for i in range(20)]
    events.sort(key=lambda e: e.timestamp)
    result = detect_incidents(events, correlate(events))
    types = {(s.type, s.service) for s in result.all_signals}
    assert ("error_spike", "api") in types
    assert ("repeated_exception", "api") in types
    assert len(result.incidents) == 1
    assert all(s.basis == "observed" for s in result.incidents[0].signals)


def test_sparse_errors_do_not_open_incidents() -> None:
    events = steady_traffic(600)
    events += [ev(t, "api", "error") for t in (50, 170, 290, 410, 530)]
    events.sort(key=lambda e: e.timestamp)
    assert detect_incidents(events, correlate(events)).incidents == []


def test_latency_increase_detected() -> None:
    events = steady_traffic(600)
    events += [ev(301 + i, "api", duration_ms=900.0) for i in range(0, 60, 2)]
    events.sort(key=lambda e: e.timestamp)
    signals = detect_incidents(events, correlate(events)).all_signals
    latency = [s for s in signals if s.type == "latency_increase"]
    assert latency and latency[0].service == "api"
    assert latency[0].metrics["window_p90_ms"] > latency[0].metrics["baseline_p90_ms"]


def test_implicit_version_change_point() -> None:
    events = [ev(0, "api", deployment_version="1.0"), ev(5, "api", deployment_version="1.1")]
    points = find_change_points(events)
    assert len(points) == 1
    assert points[0].kind == "version_change"
    assert points[0].previous_version == "1.0"


def test_explicit_deployment_suppresses_implicit_duplicate() -> None:
    events = [
        ev(0, "api", deployment_version="1.0"),
        ev(4, "api", event_type="deployment", deployment_version="1.1"),
        ev(5, "api", deployment_version="1.1"),
    ]
    assert [p.kind for p in find_change_points(events)] == ["deployment"]


@pytest.mark.parametrize("name", ["healthy-control", "unrelated-noise"])
def test_control_scenarios_produce_no_incidents(name: str) -> None:
    events = scenario_events(name)
    assert detect_incidents(events, correlate(events)).incidents == []


def test_faulty_deployment_is_an_inferred_regression() -> None:
    events = scenario_events("faulty-deployment")
    result = detect_incidents(events, correlate(events))
    assert len(result.incidents) == 1
    regression = [s for s in result.incidents[0].signals if s.type == "deployment_regression"]
    assert regression and regression[0].basis == "inferred"
    assert regression[0].service == "inventory-service"


def test_retry_storm_signal() -> None:
    events = scenario_events("retry-storm")
    signals = detect_incidents(events, correlate(events)).all_signals
    storm = [s for s in signals if s.type == "retry_storm"]
    assert storm and storm[0].service == "orders-service"
    assert storm[0].target_service == "inventory-service"


def test_missing_trace_context_is_reported_as_data_quality() -> None:
    events = scenario_events("ambiguous-partition")
    result = detect_incidents(events, correlate(events))
    assert any(s.type == "missing_trace_context" for s in result.data_quality)


def test_signal_ids_are_deterministic() -> None:
    events = scenario_events("cache-failure")
    first = [s.as_dict() for s in detect_incidents(events, correlate(events)).all_signals]
    second = [s.as_dict() for s in detect_incidents(events, correlate(events)).all_signals]
    assert first == second


def test_empty_input() -> None:
    result = detect_incidents([], correlate([]))
    assert result.incidents == [] and result.all_signals == []
