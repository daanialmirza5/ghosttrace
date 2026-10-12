"""Ingestion pipeline: bytes -> validated, de-duplicated canonical events + a summary.

This module is pure (no database access) so it can be tested and benchmarked directly.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from app.schemas.events import CanonicalEvent
from app.services.ingestion.parsers import (
    FileFormatError,
    Format,
    ParsedItem,
    PositionKind,
    decode_text,
    detect_format,
    parse_csv,
    parse_json_document,
    parse_jsonl,
    validate_field_mapping,
)
from app.services.normalization import NormalizationError, normalize_record


@dataclass(frozen=True)
class IngestionLimits:
    max_records: int = 50_000
    max_line_bytes: int = 64 * 1024
    max_reported_errors: int = 200
    max_attributes: int = 64


@dataclass(frozen=True)
class RecordError:
    position: int
    kind: PositionKind
    message: str
    field: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "position": self.position,
            "kind": self.kind,
            "message": self.message,
            "field": self.field,
        }


@dataclass
class IngestionSummary:
    format: Format | None
    total_records: int = 0
    accepted: int = 0
    rejected: int = 0
    duplicates: int = 0
    warnings: Counter[str] = field(default_factory=Counter)
    errors: list[RecordError] = field(default_factory=list)
    errors_truncated: bool = False
    file_error: str | None = None
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    services: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.file_error is not None or self.accepted == 0:
            return "failed"
        return "completed_with_errors" if self.rejected else "completed"


@dataclass
class IngestionResult:
    events: list[CanonicalEvent]
    summary: IngestionSummary


def _fingerprint(event: CanonicalEvent) -> str:
    payload = event.model_dump_json(exclude={"event_id_derived"})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ingest_bytes(
    content: bytes,
    *,
    filename: str | None = None,
    declared_format: Format | None = None,
    field_mapping: dict[str, str] | None = None,
    limits: IngestionLimits | None = None,
) -> IngestionResult:
    limits = limits or IngestionLimits()
    summary = IngestionSummary(format=declared_format)
    events: list[CanonicalEvent] = []

    def fail(message: str) -> IngestionResult:
        summary.file_error = message
        return IngestionResult(events=[], summary=summary)

    try:
        text = decode_text(content)
        if not text.strip():
            return fail("file is empty")
        fmt = declared_format or detect_format(filename, text)
        summary.format = fmt
        if fmt == "csv":
            mapping = validate_field_mapping(field_mapping) if field_mapping else None
            items = parse_csv(text, mapping, limits.max_line_bytes)
        elif field_mapping:
            return fail("field mapping is only supported for CSV files")
        elif fmt == "jsonl":
            items = parse_jsonl(text, limits.max_line_bytes)
        else:
            items = parse_json_document(text)

        # event_id -> (first event, position). Content is only hashed on an ID collision.
        seen: dict[str, tuple[CanonicalEvent, int]] = {}
        for item in items:
            summary.total_records += 1
            if summary.total_records > limits.max_records:
                return fail(
                    f"file contains more than {limits.max_records} records; "
                    "split it or raise GHOSTTRACE_MAX_RECORDS_PER_IMPORT"
                )
            _process(item, summary, events, seen, limits)
    except FileFormatError as exc:
        return fail(str(exc))

    if summary.total_records == 0:
        return fail("file contains no records")
    if events:
        summary.first_event_at = min(event.timestamp for event in events)
        summary.last_event_at = max(event.timestamp for event in events)
        summary.services = sorted({event.service for event in events})
    events.sort(key=lambda event: (event.timestamp, event.event_id))
    return IngestionResult(events=events, summary=summary)


def _process(
    item: ParsedItem,
    summary: IngestionSummary,
    events: list[CanonicalEvent],
    seen: dict[str, tuple[CanonicalEvent, int]],
    limits: IngestionLimits,
) -> None:
    def reject(message: str, field_name: str | None = None) -> None:
        summary.rejected += 1
        if len(summary.errors) < limits.max_reported_errors:
            summary.errors.append(RecordError(item.position, item.kind, message, field_name))
        else:
            summary.errors_truncated = True

    if item.error is not None:
        reject(item.error)
        return
    try:
        normalized = normalize_record(item.record, max_attributes=limits.max_attributes)
    except NormalizationError as exc:
        reject(exc.message, exc.field)
        return

    event = normalized.event
    previous = seen.get(event.event_id)
    if previous is not None:
        previous_event, previous_position = previous
        if _fingerprint(previous_event) == _fingerprint(event):
            summary.duplicates += 1
            summary.warnings["duplicate_skipped"] += 1
        else:
            reject(
                f"event_id {event.event_id!r} was already used at {item.kind} "
                f"{previous_position} with different content",
                "event_id",
            )
        return

    seen[event.event_id] = (event, item.position)
    summary.accepted += 1
    summary.warnings.update(normalized.warnings)
    if event.event_id_derived:
        summary.warnings["event_id_derived"] += 1
    events.append(event)
