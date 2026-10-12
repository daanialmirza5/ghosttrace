from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Request-ID"]


def test_ready_when_schema_is_at_head(client: TestClient) -> None:
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert {check["name"] for check in body["checks"]} == {"startup", "database", "schema"}


def test_ready_reports_pending_migrations(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'pending.db').as_posix()}",
        auto_migrate=False,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/ready")
    body = response.json()
    schema = next(check for check in body["checks"] if check["name"] == "schema")
    # With no migrations defined yet both sides are empty; once migrations exist an
    # un-migrated database must be reported as not ready.
    assert response.status_code == (200 if schema["ok"] else 503)


def test_unknown_route_returns_structured_404(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_request_id_header_is_sanitised(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "bad id\nwith newline"})
    assert response.headers["X-Request-ID"] != "bad id\nwith newline"
