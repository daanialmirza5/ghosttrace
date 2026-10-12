"""Turn heterogeneous raw records into ``CanonicalEvent`` objects.

Rules (documented in docs/event-format.md):

* Field names are matched case-insensitively against ``FIELD_ALIASES``. If two aliases of
  the same canonical field carry *different* values the record is rejected.
* Timestamps may be ISO 8601 strings or Unix epochs in seconds, milliseconds or
  microseconds. Naive ISO timestamps are interpreted as UTC and reported as a warning.
* Severity and event type must map onto the documented vocabularies; unknown values are
  rejected, never guessed. A missing event type defaults to ``log``.
* A missing event ID is derived from a SHA-256 hash of the raw record, so identical raw
  records receive identical IDs and are caught by duplicate detection.
* Unrecognised top-level fields are kept as attributes. Nested objects are flattened one
  level using dotted keys; deeper or list values are stored as compact JSON strings.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.schemas.events import AttributeValue, CanonicalEvent, EventType, Severity

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "event_id": ("event_id", "eventid", "id", "uuid", "log_id"),
    "timestamp": ("timestamp", "ts", "time", "@timestamp", "datetime", "date", "event_time"),
    "service": (
        "service",
        "service_name",
        "servicename",
        "service.name",
        "app",
        "application",
        "component",
    ),
    "environment": ("environment", "env", "deployment_environment", "deployment.environment"),
    "severity": ("severity", "level", "log_level", "loglevel", "lvl", "severity_text"),
    "event_type": ("event_type", "eventtype", "type", "kind", "category"),
    "message": ("message", "msg", "log", "text", "body"),
    "trace_id": ("trace_id", "traceid", "trace.id", "trace"),
    "span_id": ("span_id", "spanid", "span.id"),
    "parent_span_id": ("parent_span_id", "parentspanid", "parent_id", "parentid", "parent.id"),
    "request_id": ("request_id", "requestid", "correlation_id", "correlationid", "x_request_id"),
    "deployment_version": (
        "deployment_version",
        "version",
        "release",
        "service_version",
        "service.version",
        "build",
    ),
    "duration_ms": ("duration_ms", "durationms", "latency_ms", "latencyms", "elapsed_ms"),
    # "status" is intentionally not an alias: it is frequently free text ("ok", "failed").
    "status_code": ("status_code", "statuscode", "http_status", "http.status_code"),
    "target_service": (
        "target_service",
        "targetservice",
        "peer_service",
        "peer.service",
        "downstream",
        "dependency",
    ),
    "error_type": ("error_type", "errortype", "exception_type", "error_kind", "error.type"),
}

ATTRIBUTE_CONTAINERS = ("attributes", "attrs", "fields", "context", "extra")

_ALIAS_LOOKUP: dict[str, str] = {
    alias: canonical for canonical, aliases in FIELD_ALIASES.items() for alias in aliases
}

SEVERITY_ALIASES: dict[str, Severity] = {
    "trace": Severity.DEBUG,
    "debug": Severity.DEBUG,
    "info": Severity.INFO,
    "information": Severity.INFO,
    "informational": Severity.INFO,
    "notice": Severity.INFO,
    "warn": Severity.WARNING,
    "warning": Severity.WARNING,
    "err": Severity.ERROR,
    "error": Severity.ERROR,
    "crit": Severity.CRITICAL,
    "critical": Severity.CRITICAL,
    "fatal": Severity.CRITICAL,
    "alert": Severity.CRITICAL,
    "emerg": Severity.CRITICAL,
    "emergency": Severity.CRITICAL,
    "panic": Severity.CRITICAL,
}

EVENT_TYPE_ALIASES: dict[str, EventType] = {
    **{member.value: member for member in EventType},
    "message": EventType.LOG,
    "http": EventType.REQUEST,
    "http_request": EventType.REQUEST,
    "dependency": EventType.DEPENDENCY_CALL,
    "client_call": EventType.DEPENDENCY_CALL,
    "outbound": EventType.DEPENDENCY_CALL,
    "error": EventType.EXCEPTION,
    "deploy": EventType.DEPLOYMENT,
    "release": EventType.DEPLOYMENT,
    "config": EventType.CONFIG_CHANGE,
    "health": EventType.HEALTHCHECK,
}

MAX_ATTRIBUTE_KEY = 64
MAX_ATTRIBUTE_STRING = 1024
_MIN_YEAR, _MAX_YEAR = 2000, 2100


class NormalizationError(ValueError):
    """Raised when a record cannot be normalised; ``field`` names the offending field."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field = field


@dataclass(frozen=True)
class NormalizedRecord:
    event: CanonicalEvent
    warnings: list[str] = field(default_factory=list)


def parse_timestamp(value: Any) -> tuple[datetime, bool]:
    """Parse a timestamp. Returns ``(utc_datetime, was_naive)``."""
    if isinstance(value, bool) or value is None:
        raise NormalizationError("timestamp is missing or not a valid value", "timestamp")

    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise NormalizationError("timestamp is empty", "timestamp")
        try:
            numeric = float(text)
        except ValueError:
            numeric = None
        if numeric is not None:
            return _from_epoch(numeric), False
        try:
            parsed = datetime.fromisoformat(text.replace("z", "Z"))
        except ValueError as exc:
            raise NormalizationError(
                f"timestamp {text[:40]!r} is not ISO 8601 or a Unix epoch", "timestamp"
            ) from exc
        naive = parsed.tzinfo is None
        result = parsed.replace(tzinfo=UTC) if naive else parsed.astimezone(UTC)
        _check_year(result)
        return result, naive

    if isinstance(value, int | float):
        return _from_epoch(float(value)), False

    raise NormalizationError("timestamp must be a string or number", "timestamp")


def _from_epoch(value: float) -> datetime:
    if not math.isfinite(value) or value < 0:
        raise NormalizationError("epoch timestamp must be a finite positive number", "timestamp")
    # Pick the unit by magnitude: seconds (~1e9), milliseconds (~1e12), microseconds (~1e15).
    if value < 1e11:
        seconds = value
    elif value < 1e14:
        seconds = value / 1e3
    elif value < 1e17:
        seconds = value / 1e6
    else:
        raise NormalizationError("epoch timestamp magnitude not recognised", "timestamp")
    try:
        result = datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise NormalizationError("epoch timestamp out of range", "timestamp") from exc
    _check_year(result)
    return result


def _check_year(value: datetime) -> None:
    if not _MIN_YEAR <= value.year <= _MAX_YEAR:
        raise NormalizationError(
            f"timestamp year {value.year} outside supported range {_MIN_YEAR}-{_MAX_YEAR}",
            "timestamp",
        )


def _parse_severity(value: Any) -> Severity:
    if not isinstance(value, str) or not value.strip():
        raise NormalizationError("severity is missing", "severity")
    severity = SEVERITY_ALIASES.get(value.strip().lower())
    if severity is None:
        allowed = ", ".join(member.value for member in Severity)
        raise NormalizationError(
            f"unknown severity {value[:32]!r}; expected one of: {allowed}", "severity"
        )
    return severity


def _parse_event_type(value: Any) -> EventType:
    if value is None or (isinstance(value, str) and not value.strip()):
        return EventType.LOG
    if not isinstance(value, str):
        raise NormalizationError("event_type must be a string", "event_type")
    event_type = EVENT_TYPE_ALIASES.get(value.strip().lower())
    if event_type is None:
        allowed = ", ".join(member.value for member in EventType)
        raise NormalizationError(
            f"unknown event_type {value[:32]!r}; expected one of: {allowed}", "event_type"
        )
    return event_type


def _optional_str(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, (bool, Mapping, list)):
        raise NormalizationError(f"{name} must be a string", name)
    text = str(value).strip()
    return text or None


def _optional_float(value: Any, name: str) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise NormalizationError(f"{name} must be a number", name)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"{name} must be a number", name) from exc
    if not math.isfinite(number):
        raise NormalizationError(f"{name} must be finite", name)
    return number


def _optional_int(value: Any, name: str) -> int | None:
    number = _optional_float(value, name)
    if number is None:
        return None
    if not number.is_integer():
        raise NormalizationError(f"{name} must be an integer", name)
    return int(number)


def _attribute_value(value: Any) -> tuple[AttributeValue, bool]:
    """Return a JSON-scalar attribute value and whether it had to be serialised."""
    if value is None or isinstance(value, bool | int):
        return value, False
    if isinstance(value, float):
        return (value if math.isfinite(value) else str(value)), not math.isfinite(value)
    if isinstance(value, str):
        return value[:MAX_ATTRIBUTE_STRING], len(value) > MAX_ATTRIBUTE_STRING
    serialised = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return serialised[:MAX_ATTRIBUTE_STRING], True


def _derive_event_id(raw: Mapping[str, Any]) -> str:
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    return "gt-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def normalize_record(raw: Any, *, max_attributes: int = 64) -> NormalizedRecord:
    """Normalise a single raw record or raise ``NormalizationError``."""
    if not isinstance(raw, Mapping):
        raise NormalizationError("record must be a JSON object")

    canonical: dict[str, Any] = {}
    sources: dict[str, str] = {}
    attributes: dict[str, AttributeValue] = {}
    coerced = False
    warnings: list[str] = []

    def put_attribute(key: str, value: Any) -> None:
        nonlocal coerced
        clean_key = str(key)[:MAX_ATTRIBUTE_KEY]
        attr_value, was_coerced = _attribute_value(value)
        attributes[clean_key] = attr_value
        coerced = coerced or was_coerced

    for key, value in raw.items():
        lowered = str(key).strip().lower()
        if lowered in ATTRIBUTE_CONTAINERS and isinstance(value, Mapping):
            for attr_key, attr_value in value.items():
                put_attribute(str(attr_key), attr_value)
            continue
        target = _ALIAS_LOOKUP.get(lowered)
        if target is None:
            if isinstance(value, Mapping):
                for sub_key, sub_value in value.items():
                    put_attribute(f"{key}.{sub_key}", sub_value)
            else:
                put_attribute(str(key), value)
            continue
        if target in canonical and canonical[target] != value:
            raise NormalizationError(
                f"conflicting values for {target!r} in fields {sources[target]!r} and {key!r}",
                target,
            )
        canonical[target] = value
        sources[target] = str(key)

    if len(attributes) > max_attributes:
        raise NormalizationError(
            f"record has {len(attributes)} attributes; the limit is {max_attributes}",
            "attributes",
        )
    if coerced:
        warnings.append("attributes_serialised")

    timestamp, naive = parse_timestamp(canonical.get("timestamp"))
    if naive:
        warnings.append("naive_timestamp_assumed_utc")

    service = _optional_str(canonical.get("service"), "service")
    if not service:
        raise NormalizationError("service is missing", "service")

    message = canonical.get("message", "")
    if message is None:
        message = ""
    if not isinstance(message, str):
        raise NormalizationError("message must be a string", "message")

    event_id = _optional_str(canonical.get("event_id"), "event_id")
    derived = event_id is None
    if derived:
        event_id = _derive_event_id(raw)

    fields: dict[str, Any] = {
        "event_id": event_id,
        "timestamp": timestamp,
        "service": service,
        "environment": _optional_str(canonical.get("environment"), "environment") or "unknown",
        "severity": _parse_severity(canonical.get("severity")),
        "event_type": _parse_event_type(canonical.get("event_type")),
        "message": message,
        "trace_id": _optional_str(canonical.get("trace_id"), "trace_id"),
        "span_id": _optional_str(canonical.get("span_id"), "span_id"),
        "parent_span_id": _optional_str(canonical.get("parent_span_id"), "parent_span_id"),
        "request_id": _optional_str(canonical.get("request_id"), "request_id"),
        "deployment_version": _optional_str(
            canonical.get("deployment_version"), "deployment_version"
        ),
        "duration_ms": _optional_float(canonical.get("duration_ms"), "duration_ms"),
        "status_code": _optional_int(canonical.get("status_code"), "status_code"),
        "target_service": _optional_str(canonical.get("target_service"), "target_service"),
        "error_type": _optional_str(canonical.get("error_type"), "error_type"),
        "attributes": attributes,
        "event_id_derived": derived,
    }

    try:
        event = CanonicalEvent.model_validate(fields)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or None
        raise NormalizationError(
            f"{location or 'record'}: {first.get('msg', 'invalid value')}", location
        ) from exc

    return NormalizedRecord(event=event, warnings=warnings)
