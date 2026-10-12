"""Canonical event schema.

Every imported record is normalised into a ``CanonicalEvent`` before any analysis runs.
The schema is deliberately strict: values that cannot be interpreted are rejected with a
line-level error rather than coerced into something that merely looks valid.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/@-]*$"

Identifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]
ServiceName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=128, pattern=IDENTIFIER_PATTERN
    ),
]
AttributeValue = str | int | float | bool | None


class Severity(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


SEVERITY_RANK: dict[Severity, int] = {
    Severity.DEBUG: 0,
    Severity.INFO: 1,
    Severity.WARNING: 2,
    Severity.ERROR: 3,
    Severity.CRITICAL: 4,
}


class EventType(StrEnum):
    LOG = "log"
    REQUEST = "request"
    SPAN = "span"
    DEPENDENCY_CALL = "dependency_call"
    EXCEPTION = "exception"
    TIMEOUT = "timeout"
    RETRY = "retry"
    DEPLOYMENT = "deployment"
    CONFIG_CHANGE = "config_change"
    METRIC = "metric"
    HEALTHCHECK = "healthcheck"


class CanonicalEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: Identifier
    timestamp: datetime
    service: ServiceName
    environment: Identifier = "unknown"
    severity: Severity
    event_type: EventType = EventType.LOG
    message: Annotated[str, StringConstraints(max_length=8192)] = ""
    trace_id: Identifier | None = None
    span_id: Identifier | None = None
    parent_span_id: Identifier | None = None
    request_id: Identifier | None = None
    deployment_version: Identifier | None = None
    duration_ms: Annotated[float, Field(ge=0, le=86_400_000)] | None = None
    status_code: Annotated[int, Field(ge=100, le=599)] | None = None
    target_service: ServiceName | None = None
    error_type: Identifier | None = None
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)
    # True when the source record had no ID and GhostTrace derived one from its content.
    event_id_derived: bool = False

    @field_validator("timestamp")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @property
    def is_error(self) -> bool:
        return SEVERITY_RANK[self.severity] >= SEVERITY_RANK[Severity.ERROR]

    @property
    def is_warning_or_worse(self) -> bool:
        return SEVERITY_RANK[self.severity] >= SEVERITY_RANK[Severity.WARNING]


class EventOut(BaseModel):
    """API representation of a stored event."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str
    timestamp: datetime
    service: str
    environment: str
    severity: Severity
    event_type: EventType
    message: str
    trace_id: str | None
    span_id: str | None
    parent_span_id: str | None
    request_id: str | None
    deployment_version: str | None
    duration_ms: float | None
    status_code: int | None
    target_service: str | None
    error_type: str | None
    attributes: dict[str, AttributeValue]
    event_id_derived: bool
