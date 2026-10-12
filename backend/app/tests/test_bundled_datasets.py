"""The committed demo datasets import cleanly and match their ground truth."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import REPO_DIR

TRUTH = REPO_DIR / "datasets" / "ground-truth"
pytestmark = pytest.mark.skipif(
    not (REPO_DIR / "datasets" / "demo" / "catalog.json").exists(),
    reason="demo datasets not generated",
)


def test_catalog_lists_every_dataset(client: TestClient) -> None:
    names = {item["name"] for item in client.get("/api/v1/datasets/demo").json()}
    assert {"faulty-deployment", "faulty-deployment-csv", "malformed-sample"} <= names
    assert len(names) == 10


def test_malformed_sample_counts(client: TestClient) -> None:
    expected = json.loads((TRUTH / "malformed-sample.json").read_text())["expected_import"]
    body = client.post("/api/v1/datasets/demo/malformed-sample/import").json()
    assert body["total_records"] == expected["records"]
    assert body["accepted"] == expected["accepted"]
    assert body["duplicates"] == expected["duplicates"]
    assert body["rejected"] == expected["rejected"]
    assert body["status"] == "completed_with_errors"
    assert body["warnings"]["naive_timestamp_assumed_utc"] == 1


def test_csv_dataset_matches_jsonl_dataset(client: TestClient) -> None:
    jsonl = client.post("/api/v1/datasets/demo/faulty-deployment/import").json()
    csv = client.post("/api/v1/datasets/demo/faulty-deployment-csv/import").json()
    assert csv["format"] == "csv"
    assert csv["accepted"] == jsonl["accepted"] and csv["rejected"] == 0
    tops = []
    for imported in (jsonl, csv):
        incident = client.get("/api/v1/incidents", params={"import_id": imported["id"]}).json()
        tops.append(incident["items"][0]["top_service"])
    assert tops == ["inventory-service", "inventory-service"]


@pytest.mark.parametrize(
    "name",
    [
        "db-connection-exhaustion",
        "downstream-api-timeout",
        "retry-storm",
        "cache-failure",
        "healthy-control",
        "ambiguous-partition",
        "unrelated-noise",
    ],
)
def test_demo_scenarios_match_ground_truth(client: TestClient, name: str) -> None:
    truth = json.loads((TRUTH / f"{name}.json").read_text())
    imported = client.post(f"/api/v1/datasets/demo/{name}/import").json()
    assert imported["rejected"] == 0
    incidents = client.get("/api/v1/incidents", params={"import_id": imported["id"]}).json()
    if truth["expected_outcome"] == "no_incident":
        assert incidents["total"] == 0
    elif truth["expected_outcome"] == "insufficient_evidence":
        assert incidents["items"][0]["evidence_status"] == "insufficient"
    else:
        assert incidents["items"][0]["top_service"] == truth["root_cause_service"]
