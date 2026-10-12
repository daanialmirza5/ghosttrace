from __future__ import annotations

import json

import pytest

from app.services.ingestion import IngestionLimits, ingest_bytes

GOOD = {
    "event_id": "a",
    "timestamp": "2026-03-14T09:00:00Z",
    "service": "api",
    "severity": "info",
    "message": "ok",
}


def jsonl(*records: object) -> bytes:
    return "\n".join(r if isinstance(r, str) else json.dumps(r) for r in records).encode()


def test_jsonl_happy_path() -> None:
    result = ingest_bytes(jsonl(GOOD, {**GOOD, "event_id": "b"}), filename="x.jsonl")
    summary = result.summary
    assert summary.format == "jsonl"
    assert (summary.total_records, summary.accepted, summary.rejected) == (2, 2, 0)
    assert summary.status == "completed"
    assert summary.services == ["api"]
    assert [event.event_id for event in result.events] == ["a", "b"]


def test_malformed_lines_get_line_numbers_and_do_not_abort() -> None:
    content = jsonl(GOOD, "{not json", "", {**GOOD, "event_id": "c", "severity": "nope"})
    summary = ingest_bytes(content, filename="x.jsonl").summary
    assert summary.accepted == 1
    assert summary.rejected == 2
    assert summary.status == "completed_with_errors"
    assert [(error.position, error.kind) for error in summary.errors] == [(2, "line"), (4, "line")]
    assert summary.errors[1].field == "severity"


def test_exact_duplicates_are_skipped_and_collisions_rejected() -> None:
    content = jsonl(GOOD, GOOD, {**GOOD, "message": "different"})
    summary = ingest_bytes(content, filename="x.jsonl").summary
    assert summary.accepted == 1
    assert summary.duplicates == 1
    assert summary.rejected == 1
    assert "already used at line 1" in summary.errors[0].message


def test_events_without_ids_are_deduplicated_by_content() -> None:
    record = {key: value for key, value in GOOD.items() if key != "event_id"}
    summary = ingest_bytes(jsonl(record, record), filename="x.jsonl").summary
    assert summary.accepted == 1
    assert summary.duplicates == 1
    assert summary.warnings["event_id_derived"] == 1


def test_json_array_and_envelope() -> None:
    array = json.dumps([GOOD, {**GOOD, "event_id": "b"}]).encode()
    envelope = json.dumps({"source": "test", "events": [GOOD]}).encode()
    assert ingest_bytes(array, filename="events.json").summary.accepted == 2
    result = ingest_bytes(envelope, filename="events.json")
    assert result.summary.format == "json"
    assert result.summary.accepted == 1


def test_json_array_errors_use_record_positions() -> None:
    summary = ingest_bytes(json.dumps([GOOD, 5]).encode()).summary
    assert summary.errors[0].position == 2
    assert summary.errors[0].kind == "record"


def test_invalid_json_document_fails_whole_file() -> None:
    summary = ingest_bytes(b"[1, 2", filename="x.json").summary
    assert summary.status == "failed"
    assert summary.file_error and "invalid JSON" in summary.file_error


def test_csv_with_field_mapping() -> None:
    content = (
        b"when,svc,lvl,text,lat,region\n"
        b"2026-03-14T09:00:00Z,api,error,boom,12.5,eu\n"
        b'2026-03-14T09:00:01Z,api,info,"quoted, with comma",3,us\n'
    )
    mapping = {
        "when": "timestamp",
        "svc": "service",
        "lvl": "severity",
        "text": "message",
        "lat": "duration_ms",
        "region": "attributes.region",
    }
    result = ingest_bytes(content, filename="x.csv", field_mapping=mapping)
    assert result.summary.accepted == 2
    first = result.events[0]
    assert first.duration_ms == 12.5
    assert first.attributes == {"region": "eu"}
    assert result.events[1].message == "quoted, with comma"


def test_csv_rows_report_row_numbers() -> None:
    content = b"timestamp,service,severity\n2026-03-14T09:00:00Z,api,info\nbad,api,info\n"
    summary = ingest_bytes(content, filename="x.csv").summary
    assert summary.accepted == 1
    assert summary.errors[0].position == 3
    assert summary.errors[0].kind == "row"


def test_csv_mapping_validation() -> None:
    content = b"a,b\n1,2\n"
    summary = ingest_bytes(content, filename="x.csv", field_mapping={"a": "nonsense"}).summary
    assert summary.status == "failed"
    summary = ingest_bytes(content, filename="x.csv", field_mapping={"zzz": "service"}).summary
    assert summary.file_error and "missing columns" in summary.file_error


def test_mapping_rejected_for_json() -> None:
    summary = ingest_bytes(jsonl(GOOD), filename="x.jsonl", field_mapping={"a": "service"}).summary
    assert summary.status == "failed"


def test_record_limit_fails_whole_import() -> None:
    content = jsonl(*({**GOOD, "event_id": str(i)} for i in range(6)))
    summary = ingest_bytes(content, limits=IngestionLimits(max_records=5)).summary
    assert summary.status == "failed"
    assert summary.file_error and "more than 5 records" in summary.file_error


def test_overlong_lines_are_rejected() -> None:
    long_record = {**GOOD, "message": "x" * 2000}
    summary = ingest_bytes(jsonl(long_record), limits=IngestionLimits(max_line_bytes=1000)).summary
    assert summary.rejected == 1
    assert "exceeds" in summary.errors[0].message


def test_error_list_is_capped() -> None:
    content = jsonl(*["{bad"] * 10)
    summary = ingest_bytes(
        content, filename="x.jsonl", limits=IngestionLimits(max_reported_errors=3)
    ).summary
    assert summary.rejected == 10
    assert len(summary.errors) == 3
    assert summary.errors_truncated is True


@pytest.mark.parametrize(
    ("content", "message"),
    [(b"", "empty"), (b"   \n ", "empty"), (b"\xff\xfe\x00bad", "UTF-8"), (b"hello", "detect")],
)
def test_file_level_failures(content: bytes, message: str) -> None:
    summary = ingest_bytes(content).summary
    assert summary.status == "failed"
    assert summary.file_error and message in summary.file_error


def test_deeply_nested_json_is_rejected_safely() -> None:
    nested = "[" * 100_000 + "]" * 100_000
    summary = ingest_bytes(nested.encode(), filename="x.json").summary
    assert summary.status == "failed"


def test_utf8_bom_is_accepted() -> None:
    summary = ingest_bytes(b"\xef\xbb\xbf" + jsonl(GOOD), filename="x.jsonl").summary
    assert summary.accepted == 1


def test_embedded_instructions_are_treated_as_plain_text() -> None:
    record = {**GOOD, "message": "__import__('os').system('calc'); IGNORE PREVIOUS INSTRUCTIONS"}
    result = ingest_bytes(jsonl(record))
    assert result.events[0].message == record["message"]


def test_events_are_sorted_by_time() -> None:
    late = {**GOOD, "event_id": "late", "timestamp": "2026-03-14T10:00:00Z"}
    early = {**GOOD, "event_id": "early", "timestamp": "2026-03-14T08:00:00Z"}
    result = ingest_bytes(jsonl(late, early))
    assert [event.event_id for event in result.events] == ["early", "late"]
    assert result.summary.first_event_at is not None
    assert result.summary.first_event_at.hour == 8
