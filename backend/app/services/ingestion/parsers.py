"""Safe, streaming-friendly parsers for the supported upload formats.

Parsers only *decode* data: they use ``json`` and ``csv`` from the standard library and
never evaluate, import or execute uploaded content. Each parser yields
``(position, record_or_error)`` so a single bad line never aborts the whole file.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

Format = Literal["jsonl", "json", "csv"]
PositionKind = Literal["line", "record", "row"]

CANONICAL_FIELDS = frozenset(
    {
        "event_id",
        "timestamp",
        "service",
        "environment",
        "severity",
        "event_type",
        "message",
        "trace_id",
        "span_id",
        "parent_span_id",
        "request_id",
        "deployment_version",
        "duration_ms",
        "status_code",
        "target_service",
        "error_type",
    }
)


class FileFormatError(ValueError):
    """The file as a whole cannot be parsed in the requested format."""


@dataclass(frozen=True)
class ParsedItem:
    position: int
    kind: PositionKind
    record: Any = None
    error: str | None = None


def decode_text(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FileFormatError(
            f"file is not valid UTF-8 (first invalid byte at offset {exc.start})"
        ) from exc


def detect_format(filename: str | None, text: str) -> Format:
    lowered = (filename or "").lower()
    if lowered.endswith((".jsonl", ".ndjson", ".log")):
        return "jsonl"
    if lowered.endswith(".csv"):
        return "csv"
    stripped = text.lstrip()
    if stripped.startswith("["):
        return "json"
    if stripped.startswith("{"):
        # Either an envelope document {"events": [...]} or one JSON object per line.
        try:
            document = json.loads(stripped)
        except (ValueError, RecursionError):
            return "jsonl"
        if isinstance(document, dict) and isinstance(document.get("events"), list):
            return "json"
        return "jsonl"
    if lowered.endswith(".json"):
        return "json"
    raise FileFormatError("could not detect the file format; specify jsonl, json or csv")


def _loads(text: str) -> Any:
    try:
        return json.loads(text)
    except RecursionError as exc:
        raise ValueError("JSON nesting is too deep") from exc


def parse_jsonl(text: str, max_line_bytes: int) -> Iterator[ParsedItem]:
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if len(line.encode("utf-8")) > max_line_bytes:
            yield ParsedItem(number, "line", error=f"line exceeds {max_line_bytes} bytes")
            continue
        try:
            yield ParsedItem(number, "line", record=_loads(line))
        except ValueError as exc:
            yield ParsedItem(number, "line", error=f"invalid JSON: {str(exc)[:120]}")


def parse_json_document(text: str) -> Iterator[ParsedItem]:
    """A JSON array of events, or an envelope object ``{"events": [...]}``."""
    try:
        document = _loads(text)
    except ValueError as exc:
        raise FileFormatError(f"invalid JSON document: {str(exc)[:160]}") from exc
    if isinstance(document, dict):
        events = document.get("events")
        if not isinstance(events, list):
            raise FileFormatError('JSON object must contain an "events" array')
        document = events
    if not isinstance(document, list):
        raise FileFormatError("JSON document must be an array of events")
    for number, record in enumerate(document, start=1):
        yield ParsedItem(number, "record", record=record)


def validate_field_mapping(mapping: dict[str, str]) -> dict[str, str]:
    """Mapping is ``{csv_column: canonical_field}``; targets may also be ``attributes.<key>``."""
    clean: dict[str, str] = {}
    seen_targets: set[str] = set()
    for column, target in mapping.items():
        if not isinstance(column, str) or not isinstance(target, str):
            raise FileFormatError("field mapping keys and values must be strings")
        target = target.strip()
        if target not in CANONICAL_FIELDS and not (
            target.startswith("attributes.") and len(target) > len("attributes.")
        ):
            raise FileFormatError(f"field mapping target {target!r} is not a canonical field")
        if target in seen_targets and not target.startswith("attributes."):
            raise FileFormatError(f"field mapping maps more than one column to {target!r}")
        seen_targets.add(target)
        clean[column.strip()] = target
    return clean


def parse_csv(
    text: str, mapping: dict[str, str] | None, max_line_bytes: int
) -> Iterator[ParsedItem]:
    csv.field_size_limit(max_line_bytes)
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        return
    except csv.Error as exc:
        raise FileFormatError(f"invalid CSV header: {exc}") from exc
    header = [column.strip() for column in header]
    if len(set(header)) != len(header):
        raise FileFormatError("CSV header contains duplicate column names")
    mapping = mapping or {}
    unknown = sorted(set(mapping) - set(header))
    if unknown:
        raise FileFormatError(f"field mapping refers to missing columns: {', '.join(unknown)}")

    while True:
        try:
            row = next(reader)
        except StopIteration:
            return
        except csv.Error as exc:
            yield ParsedItem(reader.line_num, "row", error=f"invalid CSV: {exc}")
            return
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != len(header):
            yield ParsedItem(
                reader.line_num,
                "row",
                error=f"row has {len(row)} columns; header has {len(header)}",
            )
            continue
        record: dict[str, Any] = {}
        attributes: dict[str, Any] = {}
        for column, cell in zip(header, row, strict=True):
            value = cell.strip()
            if value == "":
                continue
            target = mapping.get(column, column)
            if target.startswith("attributes."):
                attributes[target.removeprefix("attributes.")] = value
            else:
                record[target] = value
        if attributes:
            record["attributes"] = attributes
        yield ParsedItem(reader.line_num, "row", record=record)
