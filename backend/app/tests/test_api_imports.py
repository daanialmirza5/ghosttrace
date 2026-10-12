from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

RECORDS = [
    {
        "event_id": f"e{i}",
        "timestamp": f"2026-03-14T09:00:{i:02d}Z",
        "service": "api" if i % 2 else "db",
        "severity": "error" if i == 3 else "info",
        "event_type": "span",
        "message": f"message {i}",
        "trace_id": "t1",
    }
    for i in range(10)
]


def jsonl_bytes(records: list[dict[str, object]]) -> bytes:
    return "\n".join(json.dumps(record) for record in records).encode()


def upload(client: TestClient, content: bytes, filename: str = "events.jsonl", **data: str):
    return client.post("/api/v1/imports", files={"file": (filename, content)}, data=data)


def test_upload_jsonl_and_fetch_summary(client: TestClient) -> None:
    response = upload(client, jsonl_bytes(RECORDS), name="My import")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["accepted"] == 10
    assert body["name"] == "My import"
    assert body["services"] == ["api", "db"]
    assert len(body["content_sha256"]) == 64

    fetched = client.get(f"/api/v1/imports/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]

    listing = client.get("/api/v1/imports").json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == body["id"]


def test_upload_with_errors_reports_them(client: TestClient) -> None:
    content = jsonl_bytes(RECORDS[:2]) + b"\n{broken\n"
    body = upload(client, content).json()
    assert body["status"] == "completed_with_errors"
    assert body["errors"] == [
        {"position": 3, "kind": "line", "message": body["errors"][0]["message"], "field": None}
    ]


def test_failed_file_is_stored_with_file_error(client: TestClient) -> None:
    body = upload(client, b"[1,", filename="bad.json").json()
    assert body["status"] == "failed"
    assert body["file_error"]
    assert client.get("/api/v1/imports", params={"status": "failed"}).json()["total"] == 1


def test_csv_upload_with_mapping(client: TestClient) -> None:
    content = b"t,s,l\n2026-03-14T09:00:00Z,api,warn\n"
    mapping = json.dumps({"t": "timestamp", "s": "service", "l": "severity"})
    body = upload(client, content, filename="x.csv", field_mapping=mapping).json()
    assert body["accepted"] == 1
    assert body["format"] == "csv"


def test_invalid_mapping_parameter(client: TestClient) -> None:
    response = upload(client, b"a\n1\n", filename="x.csv", field_mapping="[not an object")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unprocessable"


def test_upload_size_limit(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'size.db').as_posix()}",
        max_upload_bytes=2048,
        rate_limit_per_minute=0,
    )
    with TestClient(create_app(settings)) as client:
        response = upload(client, b"x" * 5000)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_missing_file_is_a_validation_error(client: TestClient) -> None:
    response = client.post("/api/v1/imports", data={"name": "nothing"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_event_listing_filters_and_pagination(client: TestClient) -> None:
    import_id = upload(client, jsonl_bytes(RECORDS)).json()["id"]
    url = f"/api/v1/imports/{import_id}/events"

    page = client.get(url, params={"limit": 3, "offset": 3}).json()
    assert page["total"] == 10
    assert [item["event_id"] for item in page["items"]] == ["e3", "e4", "e5"]

    errors = client.get(url, params={"severity": "error"}).json()
    assert [item["event_id"] for item in errors["items"]] == ["e3"]

    api_only = client.get(url, params={"service": "api"}).json()
    assert api_only["total"] == 5

    window = client.get(
        url, params={"start": "2026-03-14T09:00:02", "end": "2026-03-14T09:00:04Z"}
    ).json()
    assert [item["event_id"] for item in window["items"]] == ["e2", "e3", "e4"]

    search = client.get(url, params={"q": "message 7"}).json()
    assert [item["event_id"] for item in search["items"]] == ["e7"]

    wildcard = client.get(url, params={"q": "%"}).json()
    assert wildcard["total"] == 0


def test_delete_import_removes_events(client: TestClient) -> None:
    import_id = upload(client, jsonl_bytes(RECORDS)).json()["id"]
    assert client.delete(f"/api/v1/imports/{import_id}").status_code == 204
    assert client.get(f"/api/v1/imports/{import_id}").status_code == 404
    assert client.get(f"/api/v1/imports/{import_id}/events").status_code == 404


def test_unknown_import_is_404(client: TestClient) -> None:
    response = client.get("/api/v1/imports/imp_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.fixture
def demo_client(tmp_path: Path) -> TestClient:
    demo = tmp_path / "demo"
    demo.mkdir()
    (demo / "small.jsonl").write_bytes(jsonl_bytes(RECORDS))
    (tmp_path / "secret.jsonl").write_bytes(jsonl_bytes(RECORDS))
    catalog = {
        "datasets": [
            {
                "name": "small",
                "title": "Small",
                "summary": "s",
                "filename": "small.jsonl",
                "format": "jsonl",
            },
            {
                "name": "escape",
                "title": "Escape",
                "summary": "s",
                "filename": "../secret.jsonl",
                "format": "jsonl",
            },
        ]
    }
    (demo / "catalog.json").write_text(json.dumps(catalog))
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'demo.db').as_posix()}",
        demo_datasets_dir=demo,
        rate_limit_per_minute=0,
    )
    with TestClient(create_app(settings)) as client:
        yield client


def test_demo_datasets_are_listed_and_importable(demo_client: TestClient) -> None:
    listing = demo_client.get("/api/v1/datasets/demo").json()
    assert [item["name"] for item in listing] == ["small"]  # path escape is ignored
    response = demo_client.post("/api/v1/datasets/demo/small/import")
    assert response.status_code == 201
    assert response.json()["demo_dataset"] == "small"
    assert demo_client.post("/api/v1/datasets/demo/escape/import").status_code == 404
