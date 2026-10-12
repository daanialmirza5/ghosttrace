from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.analysis import analyze
from app.services.replay import ReplayFilter, ReplayTooLargeError, build_replay
from app.simulation import generate_scenario
from app.tests.factories import ev, scenario_events


def fold(replay: dict, upto: int) -> dict[str, str]:
    state = dict(replay["initial_state"])
    for frame in replay["frames"][: upto + 1]:
        state.update(frame["node_updates"])
    return state


def window(name: str):
    events = scenario_events(name)
    incident = analyze(events).incidents[0]
    return [e for e in events if incident.window_start <= e.timestamp <= incident.window_end]


def test_frames_are_ordered_and_deterministic() -> None:
    events = window("faulty-deployment")
    first = build_replay("inc", events, ReplayFilter())
    second = build_replay("inc", list(reversed(events)), ReplayFilter())
    assert first == second
    offsets = [frame["offset_ms"] for frame in first["frames"]]
    assert offsets == sorted(offsets)
    assert first["frame_count"] == len(events)
    assert [frame["index"] for frame in first["frames"]] == list(range(len(events)))


def test_root_service_becomes_failing_during_replay() -> None:
    replay = build_replay("inc", window("faulty-deployment"), ReplayFilter())
    statuses = {fold(replay, i)["inventory-service"] for i in range(replay["frame_count"])}
    assert "failing" in statuses
    assert fold(replay, 0)["inventory-service"] == "healthy"


def test_filtered_replay_agrees_with_full_replay_state() -> None:
    events = window("cache-failure")
    full = build_replay("inc", events, ReplayFilter())
    errors_only = build_replay("inc", events, ReplayFilter(severities=("error", "critical")))
    assert 0 < errors_only["frame_count"] < full["frame_count"]
    position = {frame["event_id"]: frame["index"] for frame in full["frames"]}
    for frame in errors_only["frames"][::10]:
        assert fold(errors_only, frame["index"]) == fold(full, position[frame["event_id"]])
    assert errors_only["replay_id"] != full["replay_id"]


def test_edges_are_reported_for_calls() -> None:
    replay = build_replay("inc", window("downstream-api-timeout"), ReplayFilter())
    failed = [f for f in replay["frames"] if f["edge"] and f["edge"]["failed"]]
    assert any(f["edge"]["id"] == "payments-service->payment-provider" for f in failed)


def test_frame_limit() -> None:
    events = [ev(i, "a") for i in range(20)]
    with pytest.raises(ReplayTooLargeError):
        build_replay("inc", events, ReplayFilter(), max_frames=10)


def test_empty_replay() -> None:
    replay = build_replay("inc", [], ReplayFilter())
    assert replay["frame_count"] == 0 and replay["start"] is None


def test_replay_endpoint(client: TestClient) -> None:
    content = generate_scenario("retry-storm", 42).to_jsonl().encode()
    imported = client.post("/api/v1/imports", files={"file": ("r.jsonl", content)}).json()
    incident = client.get("/api/v1/incidents", params={"import_id": imported["id"]}).json()
    incident_id = incident["items"][0]["id"]
    url = f"/api/v1/incidents/{incident_id}/replay"

    first = client.post(url, json={})
    assert first.status_code == 200
    body = first.json()
    assert body["frame_count"] == body["total_events"]
    assert client.post(url, json={}).json()["replay_id"] == body["replay_id"]

    retries = client.post(url, json={"categories": ["retry"]}).json()
    assert retries["frame_count"] > 0
    assert all(frame["category"] == "retry" for frame in retries["frames"])

    too_many = client.post(url, json={"max_frames": 1})
    assert too_many.status_code == 422
    invalid = client.post(url, json={"severities": ["loud"]})
    assert invalid.status_code == 422
