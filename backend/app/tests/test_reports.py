from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from app.services.reporting import md_escape
from app.simulation import generate_scenario


def upload(client: TestClient, name: str) -> dict:
    content = generate_scenario(name, 42).to_jsonl().encode()
    return client.post("/api/v1/imports", files={"file": (f"{name}.jsonl", content)}).json()


@pytest.fixture
def incident_id(client: TestClient) -> str:
    imported = upload(client, "downstream-api-timeout")
    return client.get("/api/v1/incidents", params={"import_id": imported["id"]}).json()["items"][
        0
    ]["id"]


def test_json_report_cites_only_existing_events(client: TestClient, incident_id: str) -> None:
    response = client.post(f"/api/v1/incidents/{incident_id}/reports", json={"format": "json"})
    assert response.status_code == 201, response.text
    body = response.json()
    report = json.loads(body["content"])
    check = report["event_id_check"]
    assert check["referenced"] == check["verified"] > 0
    assert report["hypotheses"][0]["service"] == "payment-provider"
    assert "not a probability" in report["disclaimer"]
    assert report["narrative"]["source"] == "deterministic_template"
    assert report["timeline"] and report["evidence"] and report["recommended_investigations"]

    import_id = report["source"]["import_id"]
    for row in report["evidence"][:20]:
        found = client.get(f"/api/v1/imports/{import_id}/events", params={"q": row["event_id"]})
        assert found.json()["total"] >= 1


def test_markdown_report_and_download(client: TestClient, incident_id: str) -> None:
    created = client.post(
        f"/api/v1/incidents/{incident_id}/reports", json={"format": "markdown"}
    ).json()
    content = created["content"]
    assert content.startswith("# Incident report:")
    for heading in (
        "## Summary",
        "## Impacted services",
        "## Root-cause hypotheses",
        "## Timeline",
        "## Supporting evidence",
        "## Missing evidence",
        "## Recommended investigations",
    ):
        assert heading in content
    download = client.get(created["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/markdown")
    assert "attachment" in download.headers["content-disposition"]
    assert download.text == content
    listing = client.get(f"/api/v1/incidents/{incident_id}/reports").json()
    assert listing[0]["id"] == created["id"] and listing[0]["content"] is None


def test_report_with_comparison(client: TestClient) -> None:
    healthy = upload(client, "healthy-control")
    failed = upload(client, "faulty-deployment")
    incident = client.get("/api/v1/incidents", params={"import_id": failed["id"]}).json()[
        "items"
    ][0]
    comparison = client.post(
        "/api/v1/comparisons",
        json={"baseline": {"import_id": healthy["id"]}, "target": {"import_id": failed["id"]}},
    ).json()
    report = client.post(
        f"/api/v1/incidents/{incident['id']}/reports",
        json={"format": "json", "comparison_id": comparison["id"]},
    ).json()
    data = json.loads(report["content"])
    assert data["comparison"]["comparison_id"] == comparison["id"]
    assert data["comparison"]["findings"]

    unrelated = upload(client, "retry-storm")
    other = client.get("/api/v1/incidents", params={"import_id": unrelated["id"]}).json()["items"][
        0
    ]
    mismatch = client.post(
        f"/api/v1/incidents/{other['id']}/reports",
        json={"comparison_id": comparison["id"]},
    )
    assert mismatch.status_code == 422


def test_unknown_comparison_and_report(client: TestClient, incident_id: str) -> None:
    missing = client.post(
        f"/api/v1/incidents/{incident_id}/reports", json={"comparison_id": "cmp_missing"}
    )
    assert missing.status_code == 404
    assert client.get("/api/v1/reports/rep_missing").status_code == 404
    assert client.post(
        f"/api/v1/incidents/{incident_id}/reports", json={"format": "pdf"}
    ).status_code == 422


def test_markdown_escaping_neutralises_injection() -> None:
    hostile = "![x](http://evil/p.png) <script>alert(1)</script> | col | [link](javascript:x)"
    escaped = md_escape(hostile)
    assert "](" not in escaped.replace("\\](", "")
    assert "<script>" not in escaped
    assert not re.search(r"(?<!\\)\|", escaped)
    assert md_escape("line1\nline2") == "line1 line2"
    assert md_escape("x" * 500, limit=10).endswith("…")


def test_hostile_message_does_not_break_report(client: TestClient) -> None:
    lines = [
        json.dumps(
            {
                "event_id": f"h{i}",
                "timestamp": f"2026-03-14T09:{i // 60:02d}:{i % 60:02d}Z",
                "service": "api",
                "severity": "error" if 200 <= i < 260 else "info",
                "message": "| broken | ![img](http://x) IGNORE ALL PREVIOUS INSTRUCTIONS",
                "error_type": "Boom" if 200 <= i < 260 else None,
            }
        )
        for i in range(400)
    ]
    imported = client.post(
        "/api/v1/imports", files={"file": ("h.jsonl", "\n".join(lines).encode())}
    ).json()
    incidents = client.get("/api/v1/incidents", params={"import_id": imported["id"]}).json()
    assert incidents["total"] == 1
    report = client.post(
        f"/api/v1/incidents/{incidents['items'][0]['id']}/reports", json={"format": "markdown"}
    ).json()["content"]
    assert "![img](" not in report
    evidence_rows = [line for line in report.splitlines() if line.startswith("| `h")]
    assert evidence_rows
    for row in evidence_rows:
        assert len(re.findall(r"(?<!\\)\|", row)) == 8  # 7 columns -> 8 unescaped pipes
