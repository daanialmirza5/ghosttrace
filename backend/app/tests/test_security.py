from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models.base import utcnow
from app.models.imports import ImportRecord


def make_client(tmp_path: Path, **overrides: object) -> TestClient:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'sec.db').as_posix()}",
        **{"rate_limit_per_minute": 0, "retention_hours": 0, **overrides},
    )
    return TestClient(create_app(settings))


def test_security_headers(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_cors_allows_only_configured_origins(client: TestClient) -> None:
    allowed = client.get("/api/v1/health", headers={"Origin": "http://localhost:5173"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    denied = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in denied.headers


def test_declared_oversized_body_is_rejected(tmp_path: Path) -> None:
    with make_client(tmp_path, max_upload_bytes=2048) as client:
        response = client.post(
            "/api/v1/comparisons",
            content=b"x" * (2048 + 2 * 1024 * 1024),
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_chunked_oversized_body_is_rejected(tmp_path: Path) -> None:
    def chunks():
        for _ in range(40):
            yield b"y" * 65536

    with make_client(tmp_path, max_upload_bytes=1024) as client:
        response = client.post(
            "/api/v1/comparisons", content=chunks(), headers={"content-type": "application/json"}
        )
    assert response.status_code == 413


def test_rate_limit_applies_to_mutating_requests_only(tmp_path: Path) -> None:
    with make_client(tmp_path, rate_limit_per_minute=3) as client:
        codes = [client.post("/api/v1/comparisons", json={}).status_code for _ in range(4)]
        assert codes[:3] == [422, 422, 422]
        assert codes[3] == 429
        limited = client.post("/api/v1/comparisons", json={})
        assert int(limited.headers["retry-after"]) >= 1
        assert all(client.get("/api/v1/health").status_code == 200 for _ in range(10))


def test_unexpected_errors_do_not_leak_details(tmp_path: Path) -> None:
    app = create_app(
        Settings(environment="test", database_url=f"sqlite:///{(tmp_path / 'e.db').as_posix()}")
    )

    @app.get("/api/v1/boom")
    def boom() -> None:
        raise RuntimeError("secret connection string postgres://user:pw@host")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/boom")
    assert response.status_code == 500
    assert "secret" not in response.text
    assert response.json()["error"]["request_id"]


def test_settings_never_expose_secrets(tmp_path: Path) -> None:
    with make_client(tmp_path, ai_provider="anthropic", ai_api_key="sk-ant-very-secret") as client:
        body = client.get("/api/v1/settings").text
    assert "sk-ant-very-secret" not in body
    assert '"ai_enabled":true' in body


def test_docs_can_be_disabled(tmp_path: Path) -> None:
    with make_client(tmp_path, enable_docs=False) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_retention_purges_old_imports_on_startup(tmp_path: Path) -> None:
    db = f"sqlite:///{(tmp_path / 'ret.db').as_posix()}"
    with TestClient(create_app(Settings(environment="test", database_url=db))) as client:
        client.post(
            "/api/v1/imports",
            files={
                "file": ("a.jsonl", b'{"timestamp":1773478800,"service":"a","severity":"info"}')
            },
        )
        session = client.app.state.database.session_factory()
        record = session.query(ImportRecord).one()
        record.created_at = utcnow() - timedelta(hours=48)
        session.commit()
        session.close()
    settings = Settings(environment="test", database_url=db, retention_hours=24)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/imports").json()["total"] == 0
