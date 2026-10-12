"""Request-level microservice simulator.

Topology (``->`` means "calls")::

    web-frontend -> api-gateway -> inventory-service -> redis-cache, inventory-db
                                -> orders-service    -> inventory-service, orders-db
                                -> payments-service  -> payment-provider (external)

Traced services emit one ``span`` event per handled request. Calls to datastores and the
external payment provider are recorded by the *caller* as ``dependency_call`` events, as an
OpenTelemetry client span would be. Datastores emit their own (untraced) log lines only
when a fault makes them do so, and ``payment-provider`` never emits events at all.

All randomness comes from a single ``random.Random(seed)`` so output is reproducible.
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

TRACED_SERVICES = (
    "web-frontend",
    "api-gateway",
    "orders-service",
    "payments-service",
    "inventory-service",
)
DATASTORES = ("orders-db", "inventory-db", "redis-cache")
EXTERNAL = ("payment-provider",)

BASE_LATENCY_MS: dict[str, float] = {
    "web-frontend": 6.0,
    "api-gateway": 3.0,
    "orders-service": 9.0,
    "payments-service": 8.0,
    "inventory-service": 6.0,
    "orders-db": 5.0,
    "inventory-db": 6.0,
    "redis-cache": 1.0,
    "payment-provider": 160.0,
}

# Client-side timeouts applied by the caller of each target.
CALL_TIMEOUT_MS: dict[str, float] = {
    "api-gateway": 8000.0,
    "orders-service": 6000.0,
    "payments-service": 6000.0,
    "inventory-service": 1000.0,
    "orders-db": 2000.0,
    "inventory-db": 1500.0,
    "redis-cache": 250.0,
    "payment-provider": 3000.0,
}

INITIAL_VERSIONS: dict[str, str] = {
    "web-frontend": "5.12.0",
    "api-gateway": "3.4.1",
    "orders-service": "1.19.2",
    "payments-service": "1.8.3",
    "inventory-service": "2.3.1",
}

TRANSIENT_ERRORS = (
    ("ConnectionResetError", "connection reset by peer"),
    ("SocketTimeout", "socket read timed out after 30s"),
    ("IllegalStateException", "unexpected state while serialising response"),
)


@dataclass(frozen=True)
class SimConfig:
    seed: int
    start: datetime
    duration_s: float = 600.0
    rps: float = 0.7
    noise_error_rate: float = 0.002
    trace_coverage: float = 0.97
    tracing_enabled: bool = True
    environment: str = "production"


@dataclass
class Effect:
    """How an active fault changes one call to a target service."""

    extra_latency_ms: float = 0.0
    latency_multiplier: float = 1.0
    fail: bool = False
    status_code: int = 500
    error_type: str = "InternalError"
    message: str = "internal error"
    event_type: str = "exception"


@dataclass
class CallResult:
    end: float
    ok: bool
    status_code: int
    error_type: str | None = None
    timed_out: bool = False
    message: str = ""


@dataclass
class Ctx:
    trace_id: str | None
    parent_span_id: str | None
    request_id: str | None
    service: str


class Fault:
    """Base class: a fault is active between ``start_s`` and ``end_s`` (simulation seconds)."""

    def __init__(self, start_s: float, end_s: float) -> None:
        self.start_s = start_s
        self.end_s = end_s

    def active(self, t: float) -> bool:
        return self.start_s <= t < self.end_s

    def setup(self, sim: Simulator) -> None:
        """Emit standalone events (deployments, datastore logs) before traffic runs."""

    def effect(self, sim: Simulator, target: str, operation: str, t: float) -> Effect | None:
        return None


@dataclass
class Simulator:
    config: SimConfig
    faults: list[Fault] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.config.seed)
        self.records: list[dict[str, Any]] = []
        self.versions = dict(INITIAL_VERSIONS)
        # (max_attempts, backoff_ms) used by orders-service when calling inventory-service.
        self.retry_policy: tuple[int, float] = (2, 250.0)
        self.policy_changes: list[tuple[float, tuple[int, float]]] = []
        self.version_changes: list[tuple[float, str, str]] = []
        self.inventory_calls: deque[float] = deque()
        self._hex = random.Random(self.config.seed ^ 0x5EED)

    # ----------------------------------------------------------------- helpers
    def ts(self, t: float) -> str:
        moment = self.config.start + timedelta(seconds=t)
        return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"

    def new_id(self, length: int) -> str:
        return f"{self._hex.getrandbits(length * 4):0{length}x}"

    def latency(self, service: str) -> float:
        return BASE_LATENCY_MS[service] * self.rng.lognormvariate(0.0, 0.35)

    def emit(self, t: float, service: str, severity: str, event_type: str, message: str,
             *, ground_truth: bool = False, **fields: Any) -> dict[str, Any]:
        record: dict[str, Any] = {
            "_t": t,
            "_gt": ground_truth,
            "timestamp": self.ts(t),
            "service": service,
            "environment": self.config.environment,
            "severity": severity,
            "event_type": event_type,
            "message": message,
        }
        if service in self.versions:
            record["deployment_version"] = self.version_at(service, t)
        record.update({key: value for key, value in fields.items() if value is not None})
        self.records.append(record)
        return record

    def version_at(self, service: str, t: float) -> str:
        version = INITIAL_VERSIONS.get(service, "1.0.0")
        for when, changed, new_version in self.version_changes:
            if changed == service and when <= t:
                version = new_version
        return version

    def policy_at(self, t: float) -> tuple[int, float]:
        policy = self.retry_policy
        for when, new_policy in self.policy_changes:
            if when <= t:
                policy = new_policy
        return policy

    def fault_effect(self, target: str, operation: str, t: float) -> Effect | None:
        for fault in self.faults:
            if fault.active(t):
                effect = fault.effect(self, target, operation, t)
                if effect is not None:
                    return effect
        return None

    def record_inventory_call(self, t: float) -> None:
        self.inventory_calls.append(t)

    def inventory_load(self, t: float, window_s: float) -> int:
        """Number of calls inventory-service received in the last ``window_s`` seconds."""
        while self.inventory_calls and self.inventory_calls[0] < t - window_s:
            self.inventory_calls.popleft()
        return len(self.inventory_calls)

    def trace_fields(self, ctx: Ctx, span_id: str) -> dict[str, Any]:
        if not self.config.tracing_enabled:
            return {}
        parent = ctx.parent_span_id
        # A small fraction of spans lose their parent link, as in real instrumentation.
        if parent is not None and self.rng.random() > self.config.trace_coverage:
            parent = None
        return {
            "trace_id": ctx.trace_id,
            "span_id": span_id,
            "parent_span_id": parent,
            "request_id": ctx.request_id,
        }

    # ------------------------------------------------------------- execution
    def run(self) -> list[dict[str, Any]]:
        for fault in self.faults:
            fault.setup(self)
        t = self.rng.expovariate(self.config.rps)
        while t < self.config.duration_s:
            self.request(t)
            t += self.rng.expovariate(self.config.rps)
        self.records.sort(key=lambda record: (record["_t"], record["service"], record["message"]))
        return self.records

    def request(self, t: float) -> None:
        roll = self.rng.random()
        operation = "browse" if roll < 0.5 else ("checkout" if roll < 0.75 else "order_status")
        trace_id = self.new_id(32) if self.config.tracing_enabled else None
        request_id = f"req-{self.new_id(12)}" if self.config.tracing_enabled else None
        root = Ctx(trace_id=trace_id, parent_span_id=None, request_id=request_id, service="user")
        self.call_service(root, "web-frontend", operation, t)

    def call_service(self, ctx: Ctx, target: str, operation: str, t: float) -> CallResult:
        """Call a traced service; returns what the caller observes."""
        span_id = self.new_id(16)
        child_ctx = Ctx(ctx.trace_id, span_id, ctx.request_id, target)
        effect = self.fault_effect(target, operation, t)
        if target == "inventory-service":
            self.record_inventory_call(t)

        cursor = t + self.latency(target) * 0.3 / 1000.0
        result = CallResult(end=cursor, ok=True, status_code=200)
        if effect is None or not effect.fail:
            result = self.handle(child_ctx, target, operation, cursor)
        if effect is not None:
            result.end += effect.extra_latency_ms / 1000.0
        own = self.latency(target) * (effect.latency_multiplier if effect else 1.0)
        end = max(result.end, cursor) + own / 1000.0

        severity = "info"
        message = f"{operation} handled"
        status = result.status_code
        error_type = result.error_type
        event_type = "span" if self.config.tracing_enabled else "request"
        if effect is not None and effect.fail:
            status, error_type = effect.status_code, effect.error_type
            message = f"{operation} failed: {effect.message}"
            severity = "error"
            event_type = effect.event_type if effect.event_type != "span" else event_type
        elif not result.ok:
            severity = "error"
            message = f"{operation} failed: {result.message or 'dependency failure'}"
        elif self.rng.random() < self.config.noise_error_rate:
            error_type, detail = self.rng.choice(TRANSIENT_ERRORS)
            status, severity = 500, "error"
            message = f"{operation} failed: {detail}"

        ok = severity != "error"
        duration = (end - t) * 1000.0
        self.emit(
            end,
            target,
            severity,
            event_type,
            message,
            duration_ms=round(duration, 2),
            status_code=status if ok else max(status, 500),
            error_type=None if ok else error_type,
            attributes={"operation": operation},
            **self.trace_fields(ctx, span_id),
        )
        timeout_ms = CALL_TIMEOUT_MS.get(target, 10_000.0)
        if duration > timeout_ms:
            return CallResult(
                end=t + timeout_ms / 1000.0,
                ok=False,
                status_code=504,
                error_type="Timeout",
                timed_out=True,
                message=f"{target} did not respond within {int(timeout_ms)}ms",
            )
        return CallResult(
            end=end,
            ok=ok,
            status_code=status if ok else max(status, 500),
            error_type=error_type if not ok else None,
            message="" if ok else f"{target} returned {max(status, 500)}",
        )

    def call_dependency(self, ctx: Ctx, target: str, operation: str, t: float) -> CallResult:
        """Call a datastore or external API; the caller emits a dependency_call event."""
        effect = self.fault_effect(target, operation, t)
        latency = self.latency(target)
        if effect is not None:
            latency = latency * effect.latency_multiplier + effect.extra_latency_ms
        timeout_ms = CALL_TIMEOUT_MS[target]
        timed_out = latency > timeout_ms
        observed = min(latency, timeout_ms)
        end = t + observed / 1000.0
        failed = timed_out or (effect is not None and effect.fail)

        if not self.config.tracing_enabled:
            # Without instrumentation, outbound calls are not recorded at all.
            if failed:
                return CallResult(end, False, 503, effect.error_type if effect else "Timeout")
            return CallResult(end, True, 200)

        span_id = self.new_id(16)
        fields = self.trace_fields(ctx, span_id)
        if timed_out:
            self.emit(
                end, ctx.service, "error", "timeout",
                f"{operation} on {target} timed out after {int(timeout_ms)}ms",
                target_service=target, duration_ms=round(observed, 2),
                error_type="ReadTimeout", attributes={"operation": operation}, **fields,
            )
            return CallResult(end, False, 504, "ReadTimeout", timed_out=True,
                              message=f"{target} timed out")
        if effect is not None and effect.fail:
            self.emit(
                end, ctx.service, "error", "dependency_call",
                f"{operation} on {target} failed: {effect.message}",
                target_service=target, duration_ms=round(observed, 2),
                error_type=effect.error_type, attributes={"operation": operation}, **fields,
            )
            return CallResult(end, False, effect.status_code, effect.error_type,
                              message=f"{target}: {effect.message}")
        severity = "warning" if observed > timeout_ms * 0.6 else "info"
        self.emit(
            end, ctx.service, severity, "dependency_call",
            f"{operation} on {target} completed" + (" slowly" if severity == "warning" else ""),
            target_service=target, duration_ms=round(observed, 2),
            attributes={"operation": operation}, **fields,
        )
        return CallResult(end, True, 200)

    # --------------------------------------------------------------- handlers
    def handle(self, ctx: Ctx, service: str, operation: str, t: float) -> CallResult:
        if service == "web-frontend":
            return self.call_service(ctx, "api-gateway", operation, t)
        if service == "api-gateway":
            if operation == "browse":
                return self.call_service(ctx, "inventory-service", "get_item", t)
            if operation == "order_status":
                return self.call_service(ctx, "orders-service", "get_order", t)
            order = self.call_service(ctx, "orders-service", "create_order", t)
            if not order.ok:
                return order
            return self.call_service(ctx, "payments-service", "charge", order.end)
        if service == "orders-service":
            if operation == "get_order":
                return self.call_dependency(ctx, "orders-db", "SELECT orders", t)
            reserved = self.reserve_with_retries(ctx, t)
            if not reserved.ok:
                return reserved
            return self.call_dependency(ctx, "orders-db", "INSERT orders", reserved.end)
        if service == "payments-service":
            return self.call_dependency(ctx, "payment-provider", "POST /v1/charges", t)
        if service == "inventory-service":
            if operation == "reserve":
                return self.call_dependency(ctx, "inventory-db", "UPDATE stock", t)
            cached = self.call_dependency(ctx, "redis-cache", "GET item", t)
            if cached.ok and self.rng.random() < 0.8:
                return cached
            loaded = self.call_dependency(ctx, "inventory-db", "SELECT items", cached.end)
            if loaded.ok and cached.ok:
                return self.call_dependency(ctx, "redis-cache", "SET item", loaded.end)
            return loaded
        raise ValueError(f"unknown service {service}")

    def reserve_with_retries(self, ctx: Ctx, t: float) -> CallResult:
        max_attempts, backoff_ms = self.policy_at(t)
        cursor = t
        result = self.call_service(ctx, "inventory-service", "reserve", cursor)
        attempt = 1
        while not result.ok and attempt < max_attempts:
            delay = backoff_ms * (2 ** (attempt - 1)) / 1000.0
            cursor = result.end + delay
            attempt += 1
            fields = self.trace_fields(ctx, self.new_id(16)) if self.config.tracing_enabled else {}
            self.emit(
                cursor, "orders-service", "warning", "retry",
                f"retrying reserve on inventory-service (attempt {attempt}/{max_attempts}) "
                f"after {result.error_type or 'error'}",
                target_service="inventory-service" if self.config.tracing_enabled else None,
                attributes={"retry_attempt": attempt, "max_attempts": max_attempts,
                            "backoff_ms": backoff_ms},
                **fields,
            )
            result = self.call_service(ctx, "inventory-service", "reserve", cursor)
        return result
