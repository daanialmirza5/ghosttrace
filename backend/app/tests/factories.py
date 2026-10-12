"""Helpers for building canonical events in tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

from app.schemas.events import CanonicalEvent
from app.services.ingestion import ingest_bytes
from app.simulation import generate_scenario

BASE = datetime(2026, 3, 14, 9, 0, 0, tzinfo=UTC)
_ids = count(1)


def ev(
    seconds: float,
    service: str,
    severity: str = "info",
    event_type: str = "span",
    **fields: Any,
) -> CanonicalEvent:
    return CanonicalEvent.model_validate(
        {
            "event_id": fields.pop("event_id", f"t-{next(_ids):06d}"),
            "timestamp": BASE + timedelta(seconds=seconds),
            "service": service,
            "severity": severity,
            "event_type": event_type,
            "message": fields.pop("message", f"{service} {event_type}"),
            **fields,
        }
    )


def scenario_events(name: str, seed: int = 42) -> list[CanonicalEvent]:
    generated = generate_scenario(name, seed)
    return ingest_bytes(generated.to_jsonl().encode(), filename=f"{name}.jsonl").events
