from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.comparison import compare_profiles, profile_events
from app.simulation import generate_scenario
from app.tests.factories import ev, scenario_events


def test_healthy_vs_faulty_deployment_highlights_the_regression() -> None:
    result = compare_profiles(
        profile_events("healthy", scenario_events("healthy-control")),
        profile_events("failed", scenario_events("faulty-deployment")),
    )
    assert result["comparable"] is True
    inventory = next(row for row in result["services"] if row["service"] == "inventory-service")
    assert inventory["target_error_rate"] > inventory["baseline_error_rate"]
    assert inventory["baseline_versions"] == ["2.3.1"]
    assert inventory["target_versions"] == ["2.3.1", "2.4.0"]
    kinds = {(f["kind"], f["service"]) for f in result["findings"]}
    assert ("error_rate", "inventory-service") in kinds
    assert ("version", "inventory-service") in kinds


def test_latency_without_measurements_is_labelled_not_zero() -> None:
    baseline = [ev(i, "a") for i in range(30)] + [ev(i, "b", duration_ms=10.0) for i in range(40)]
    target = [ev(i, "a") for i in range(30)] + [ev(i, "b", duration_ms=50.0) for i in range(40)]
    result = compare_profiles(profile_events("x", baseline), profile_events("y", target))
    row_a = next(row for row in result["services"] if row["service"] == "a")
    assert row_a["baseline_p95_ms"] is None and row_a["p95_ratio"] is None
    assert row_a["latency_note"] == "not measured in either execution"
    row_b = next(row for row in result["services"] if row["service"] == "b")
    assert row_b["p95_ratio"] == 5.0


def test_disjoint_systems_are_incomparable() -> None:
    left = [ev(i, "alpha") for i in range(40)]
    right = [ev(i, "omega") for i in range(40)]
    result = compare_profiles(profile_events("l", left), profile_events("r", right))
    assert result["comparable"] is False
    assert any("overlap" in reason for reason in result["incomparable_reasons"])


def test_too_little_data_is_incomparable() -> None:
    result = compare_profiles(
        profile_events("l", [ev(0, "a")]), profile_events("r", [ev(i, "a") for i in range(40)])
    )
    assert result["comparable"] is False
    assert any("only 1 events" in reason for reason in result["incomparable_reasons"])


def test_window_length_difference_warns() -> None:
    short = [ev(i, "a") for i in range(60)]
    long = [ev(i * 10, "a") for i in range(60)]
    result = compare_profiles(profile_events("s", short), profile_events("l", long))
    assert any("normalised per minute" in warning for warning in result["warnings"])


def test_comparison_api(client: TestClient) -> None:
    def upload(name: str) -> str:
        content = generate_scenario(name, 42).to_jsonl().encode()
        return client.post("/api/v1/imports", files={"file": (f"{name}.jsonl", content)}).json()[
            "id"
        ]

    healthy, failed = upload("healthy-control"), upload("cache-failure")
    incident = client.get("/api/v1/incidents", params={"import_id": failed}).json()["items"][0]
    response = client.post(
        "/api/v1/comparisons",
        json={
            "baseline": {"import_id": healthy, "label": "healthy"},
            "target": {"import_id": failed, "incident_id": incident["id"], "label": "incident"},
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["comparable"] is True
    assert body["baseline"]["label"] == "healthy"
    assert body["findings"]
    assert client.get(f"/api/v1/comparisons/{body['id']}").json()["id"] == body["id"]
    assert client.get("/api/v1/comparisons").json()["total"] == 1

    wrong_incident = client.post(
        "/api/v1/comparisons",
        json={
            "baseline": {"import_id": healthy, "incident_id": incident["id"]},
            "target": {"import_id": failed},
        },
    )
    assert wrong_incident.status_code == 422

    bad_window = client.post(
        "/api/v1/comparisons",
        json={
            "baseline": {
                "import_id": healthy,
                "start": "2026-03-14T09:05:00Z",
                "end": "2026-03-14T09:00:00Z",
            },
            "target": {"import_id": failed},
        },
    )
    assert bad_window.status_code == 422

    client.delete(f"/api/v1/imports/{healthy}")
    assert client.get(f"/api/v1/comparisons/{body['id']}").status_code == 404
