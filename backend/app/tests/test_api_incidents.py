from __future__ import annotations

from datetime import datetime
from functools import cache

import pytest
from fastapi.testclient import TestClient

from app.simulation import generate_scenario


@cache
def scenario_bytes(name: str) -> bytes:
    return generate_scenario(name, 42).to_jsonl().encode()


def upload_scenario(client: TestClient, name: str) -> dict:
    response = client.post(
        "/api/v1/imports", files={"file": (f"{name}.jsonl", scenario_bytes(name))}
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def deployment(client: TestClient) -> tuple[dict, dict]:
    imported = upload_scenario(client, "faulty-deployment")
    incidents = client.get("/api/v1/incidents", params={"import_id": imported["id"]}).json()
    return imported, incidents["items"][0]


def test_import_runs_analysis(deployment: tuple[dict, dict]) -> None:
    imported, incident = deployment
    assert imported["analysis_status"] == "completed"
    assert imported["incident_count"] == 1
    assert imported["analysis_ms"] > 0
    assert incident["top_service"] == "inventory-service"
    assert incident["evidence_status"] == "sufficient"
    assert incident["import_name"] == "faulty-deployment.jsonl"


def test_incident_detail_references_existing_events(
    client: TestClient, deployment: tuple[dict, dict]
) -> None:
    imported, summary = deployment
    detail = client.get(f"/api/v1/incidents/{summary['id']}").json()
    assert detail["hypotheses"][0]["rank"] == 1
    assert detail["hypotheses"][0]["score_label"] == "heuristic score (not a probability)"
    assert {s["basis"] for s in detail["signals"]} == {"observed", "inferred"}

    referenced: set[str] = set()
    for signal in detail["signals"]:
        referenced.update(signal["evidence_event_ids"])
    for hypothesis in detail["hypotheses"]:
        referenced.update(hypothesis["supporting_event_ids"])
    for event_id in sorted(referenced)[:40]:
        page = client.get(f"/api/v1/imports/{imported['id']}/events", params={"q": event_id})
        assert page.json()["total"] >= 1, event_id


def test_hypotheses_endpoint_documents_method(
    client: TestClient, deployment: tuple[dict, dict]
) -> None:
    _, summary = deployment
    body = client.get(f"/api/v1/incidents/{summary['id']}/hypotheses").json()
    assert body["evidence_status"] == "sufficient"
    assert "not a probability" in body["method"]["description"]
    assert sum(body["method"]["weights"].values()) == pytest.approx(1.0)
    top = body["hypotheses"][0]
    assert top["service"] == "inventory-service"
    assert top["next_step"]
    assert {signal["name"] for signal in top["signals"]} == set(body["method"]["weights"])


def test_timeline_filters_and_markers(client: TestClient, deployment: tuple[dict, dict]) -> None:
    _, summary = deployment
    url = f"/api/v1/incidents/{summary['id']}/timeline"
    full = client.get(url, params={"limit": 2000}).json()
    assert full["total"] == summary["event_count"]
    assert len(full["histogram"]) == 60
    assert any(marker["kind"] == "change" for marker in full["markers"])
    timestamps = [datetime.fromisoformat(item["event"]["timestamp"]) for item in full["items"]]
    assert timestamps == sorted(timestamps)

    errors = client.get(url, params={"category": "error"}).json()
    assert errors["total"] > 0
    assert all(item["category"] == "error" for item in errors["items"])

    inventory = client.get(url, params={"service": "inventory-service", "limit": 5}).json()
    assert len(inventory["items"]) == 5
    assert all(item["event"]["service"] == "inventory-service" for item in inventory["items"])

    evidence = client.get(url, params={"evidence_only": True}).json()
    assert evidence["total"] > 0
    assert all(item["is_evidence"] for item in evidence["items"])


def test_incident_graph(client: TestClient, deployment: tuple[dict, dict]) -> None:
    _, summary = deployment
    graph = client.get(f"/api/v1/incidents/{summary['id']}/graph").json()
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["inventory-service"]["hypothesis_rank"] == 1
    assert nodes["inventory-service"]["status"] in {"failing", "degraded"}
    assert nodes["payment-provider"]["kind"] == "inferred"
    edge_ids = {edge["id"] for edge in graph["edges"]}
    assert "api-gateway->inventory-service" in edge_ids
    assert graph["scope"]["kind"] == "incident"
    assert all(edge["evidence_event_ids"] for edge in graph["edges"])


def test_import_graph(client: TestClient, deployment: tuple[dict, dict]) -> None:
    imported, _ = deployment
    graph = client.get(f"/api/v1/imports/{imported['id']}/graph").json()
    assert graph["scope"]["event_count"] == imported["accepted"]
    assert graph["entry_points"] == ["web-frontend"]


def test_event_detail_shows_references(client: TestClient, deployment: tuple[dict, dict]) -> None:
    _, summary = deployment
    detail = client.get(f"/api/v1/incidents/{summary['id']}").json()
    key_event = detail["hypotheses"][0]["key_event_id"]
    body = client.get(f"/api/v1/incidents/{summary['id']}/events/{key_event}").json()
    assert body["event"]["event_type"] == "deployment"
    assert any(ref["kind"] == "hypothesis" for ref in body["referenced_by"])

    error_id = detail["hypotheses"][0]["signals"][4]["evidence_event_ids"][0]
    traced = client.get(f"/api/v1/incidents/{summary['id']}/events/{error_id}").json()
    assert traced["relation"] == "trace"
    assert traced["related_events"]

    missing = client.get(f"/api/v1/incidents/{summary['id']}/events/nope")
    assert missing.status_code == 404


def test_healthy_import_has_no_incidents(client: TestClient) -> None:
    imported = upload_scenario(client, "healthy-control")
    assert imported["incident_count"] == 0
    assert (
        client.get("/api/v1/incidents", params={"import_id": imported["id"]}).json()["total"] == 0
    )


def test_ambiguous_import_reports_insufficient_evidence(client: TestClient) -> None:
    imported = upload_scenario(client, "ambiguous-partition")
    incidents = client.get(
        "/api/v1/incidents", params={"import_id": imported["id"], "evidence_status": "insufficient"}
    ).json()
    assert incidents["total"] == 1
    detail = client.get(f"/api/v1/incidents/{incidents['items'][0]['id']}").json()
    assert detail["data_quality"]
    assert detail["missing_information"]


def test_dashboard_summary_reflects_stored_data(
    client: TestClient, deployment: tuple[dict, dict]
) -> None:
    imported, _ = deployment
    body = client.get("/api/v1/dashboard/summary").json()
    assert body["import_count"] == 1
    assert body["event_count"] == imported["accepted"]
    assert body["incident_count"] == 1
    assert body["top_ranked_services"] == {"inventory-service": 1}
    assert body["recent_imports"][0]["incident_count"] == 1


def test_deleting_import_removes_incidents(
    client: TestClient, deployment: tuple[dict, dict]
) -> None:
    imported, summary = deployment
    assert client.delete(f"/api/v1/imports/{imported['id']}").status_code == 204
    assert client.get(f"/api/v1/incidents/{summary['id']}").status_code == 404


def test_unknown_incident(client: TestClient) -> None:
    assert client.get("/api/v1/incidents/inc_missing/timeline").status_code == 404
