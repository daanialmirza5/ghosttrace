from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def spa_client(tmp_path: Path) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "assets" / "app-123.js").write_text("console.log('ok')")
    (tmp_path / "secret.txt").write_text("do not serve")
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 's.db').as_posix()}",
        static_dir=dist,
        rate_limit_per_minute=0,
    )
    with TestClient(create_app(settings)) as client:
        yield client


def test_index_and_client_routes_serve_the_app(spa_client: TestClient) -> None:
    for path in ("/", "/incidents/inc_1/replay", "/import"):
        response = spa_client.get(path)
        assert response.status_code == 200
        assert "id=root" in response.text
        assert response.headers["cache-control"] == "no-cache"
        assert "script-src 'self'" in response.headers["content-security-policy"]


def test_assets_are_cacheable(spa_client: TestClient) -> None:
    response = spa_client.get("/assets/app-123.js")
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


def test_api_is_not_shadowed(spa_client: TestClient) -> None:
    assert spa_client.get("/api/v1/health").json()["status"] == "ok"
    missing = spa_client.get("/api/v1/nope")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert spa_client.get("/openapi.json").status_code == 200


def test_path_traversal_returns_index_not_files(spa_client: TestClient) -> None:
    response = spa_client.get("/..%2Fsecret.txt")
    assert "do not serve" not in response.text


def test_missing_index_fails_fast(tmp_path: Path) -> None:
    settings = Settings(environment="test", static_dir=tmp_path)
    with pytest.raises(RuntimeError, match=r"index\.html"):
        create_app(settings)
