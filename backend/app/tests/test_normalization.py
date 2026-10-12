from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.schemas.events import EventType, Severity
from app.services.normalization import NormalizationError, normalize_record, parse_timestamp


def base_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "event_id": "evt-1",
        "timestamp": "2026-03-14T09:00:00Z",
        "service": "orders-service",
        "severity": "error",
        "message": "boom",
    }
    record.update(overrides)
    return record


class TestTimestamps:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2026-03-14T09:00:00Z", datetime(2026, 3, 14, 9, 0, tzinfo=UTC)),
            ("2026-03-14T10:00:00+01:00", datetime(2026, 3, 14, 9, 0, tzinfo=UTC)),
            ("2026-03-14T09:00:00.250Z", datetime(2026, 3, 14, 9, 0, 0, 250000, tzinfo=UTC)),
            (1773478800, datetime(2026, 3, 14, 9, 0, tzinfo=UTC)),
            (1773478800000, datetime(2026, 3, 14, 9, 0, tzinfo=UTC)),
            (1773478800000000, datetime(2026, 3, 14, 9, 0, tzinfo=UTC)),
            ("1773478800", datetime(2026, 3, 14, 9, 0, tzinfo=UTC)),
        ],
    )
    def test_supported_formats_normalise_to_utc(self, value: object, expected: datetime) -> None:
        parsed, naive = parse_timestamp(value)
        assert parsed == expected
        assert parsed.tzinfo == UTC
        assert naive is False

    def test_naive_iso_is_assumed_utc_and_flagged(self) -> None:
        parsed, naive = parse_timestamp("2026-03-14 09:00:00")
        assert parsed == datetime(2026, 3, 14, 9, 0, tzinfo=UTC)
        assert naive is True

    @pytest.mark.parametrize(
        "value", ["yesterday", "", None, True, "nan", float("inf"), -5, "1e3", 10**18, {}]
    )
    def test_invalid_timestamps_are_rejected(self, value: object) -> None:
        with pytest.raises(NormalizationError) as info:
            parse_timestamp(value)
        assert info.value.field == "timestamp"


class TestRecordNormalisation:
    def test_canonical_record(self) -> None:
        result = normalize_record(base_record(trace_id="t1", duration_ms="12.5"))
        event = result.event
        assert event.event_id == "evt-1"
        assert event.severity is Severity.ERROR
        assert event.event_type is EventType.LOG
        assert event.duration_ms == 12.5
        assert event.environment == "unknown"
        assert result.warnings == []

    def test_aliases_are_case_insensitive(self) -> None:
        raw = {
            "ID": "a",
            "@timestamp": "2026-03-14T09:00:00Z",
            "serviceName": "api",
            "Level": "WARN",
            "msg": "slow",
            "traceId": "t",
            "latency_ms": 5,
            "type": "dependency",
            "peer.service": "db",
        }
        event = normalize_record(raw).event
        assert event.service == "api"
        assert event.severity is Severity.WARNING
        assert event.event_type is EventType.DEPENDENCY_CALL
        assert event.target_service == "db"
        assert event.trace_id == "t"

    def test_conflicting_aliases_are_rejected(self) -> None:
        with pytest.raises(NormalizationError, match="conflicting values"):
            normalize_record(base_record(level="info"))

    def test_identical_aliases_are_accepted(self) -> None:
        assert normalize_record(base_record(level="error")).event.severity is Severity.ERROR

    def test_unknown_severity_is_rejected_not_guessed(self) -> None:
        with pytest.raises(NormalizationError) as info:
            normalize_record(base_record(severity="spicy"))
        assert info.value.field == "severity"

    def test_unknown_event_type_is_rejected(self) -> None:
        with pytest.raises(NormalizationError, match="unknown event_type"):
            normalize_record(base_record(event_type="telepathy"))

    @pytest.mark.parametrize("missing", ["service", "severity", "timestamp"])
    def test_required_fields(self, missing: str) -> None:
        record = base_record()
        del record[missing]
        with pytest.raises(NormalizationError):
            normalize_record(record)

    def test_missing_event_id_is_derived_deterministically(self) -> None:
        record = base_record()
        del record["event_id"]
        first = normalize_record(record).event
        second = normalize_record(dict(record)).event
        assert first.event_id == second.event_id
        assert first.event_id.startswith("gt-")
        assert first.event_id_derived is True

    def test_unknown_fields_become_attributes(self) -> None:
        event = normalize_record(
            base_record(pool={"in_use": 20, "max": 20}, region="eu-west-1", tags=["a", "b"])
        )
        attrs = event.event.attributes
        assert attrs["pool.in_use"] == 20
        assert attrs["region"] == "eu-west-1"
        assert attrs["tags"] == '["a","b"]'
        assert "attributes_serialised" in event.warnings

    def test_attribute_container_is_flattened(self) -> None:
        event = normalize_record(base_record(attributes={"retry_attempt": 2})).event
        assert event.attributes == {"retry_attempt": 2}

    def test_attribute_limit(self) -> None:
        with pytest.raises(NormalizationError, match="attributes"):
            normalize_record(base_record(**{f"k{i}": i for i in range(70)}))

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("duration_ms", "fast"),
            ("duration_ms", -1),
            ("status_code", 99),
            ("status_code", 200.5),
            ("service", "bad service name!"),
            ("message", {"nested": True}),
            ("trace_id", ["x"]),
        ],
    )
    def test_malformed_values_are_rejected(self, field: str, value: object) -> None:
        with pytest.raises(NormalizationError):
            normalize_record(base_record(**{field: value}))

    def test_non_object_record_is_rejected(self) -> None:
        with pytest.raises(NormalizationError, match="JSON object"):
            normalize_record(["not", "an", "object"])

    def test_free_text_status_is_kept_as_attribute(self) -> None:
        event = normalize_record(base_record(status="failed")).event
        assert event.status_code is None
        assert event.attributes["status"] == "failed"
