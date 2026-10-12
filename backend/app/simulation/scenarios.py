"""The eight reproducible incident scenarios and their ground truth."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from app.simulation.simulator import Effect, Fault, SimConfig, Simulator

DEMO_START = datetime(2026, 3, 14, 9, 0, 0, tzinfo=UTC)


@dataclass(frozen=True)
class ScenarioWindow:
    start_s: float
    end_s: float


@dataclass
class GeneratedScenario:
    name: str
    events: list[dict[str, Any]]
    ground_truth: dict[str, Any]

    def to_jsonl(self) -> str:
        return "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in self.events)

    def sha256(self) -> str:
        return hashlib.sha256(self.to_jsonl().encode("utf-8")).hexdigest()


# ------------------------------------------------------------------- faults
class DatabaseConnectionExhaustion(Fault):
    """orders-db runs out of connection slots; orders-service calls start timing out."""

    def setup(self, sim: Simulator) -> None:
        t = self.start_s
        while t < self.start_s + 60:
            used = min(100, 80 + int((t - self.start_s) / 3))
            sim.emit(
                t,
                "orders-db",
                "warning",
                "log",
                f"connection count high: {used}/100 slots in use",
                ground_truth=t == self.start_s,
                attributes={"connections_in_use": used, "max_connections": 100},
            )
            t += 6 + sim.rng.random() * 2

    def effect(self, sim: Simulator, target: str, operation: str, t: float) -> Effect | None:
        if target != "orders-db":
            return None
        if t < self.start_s + 60:
            return Effect(latency_multiplier=4.0)
        if sim.rng.random() < 0.85:
            if sim.rng.random() < 0.5:
                sim.emit(
                    t,
                    "orders-db",
                    "error",
                    "log",
                    "FATAL: sorry, too many clients already",
                    error_type="TooManyConnections",
                    attributes={"connections_in_use": 100, "max_connections": 100},
                )
            return Effect(
                extra_latency_ms=1950.0,
                fail=True,
                status_code=503,
                error_type="PoolTimeoutError",
                message="QueuePool limit reached, connection timed out",
            )
        return Effect(latency_multiplier=6.0)


class DownstreamTimeout(Fault):
    """The external payment provider slows down and then stops answering in time."""

    def effect(self, sim: Simulator, target: str, operation: str, t: float) -> Effect | None:
        if target != "payment-provider":
            return None
        if t < self.start_s + 30:
            return Effect(extra_latency_ms=800 + sim.rng.random() * 1200)
        return Effect(extra_latency_ms=2600 + sim.rng.random() * 4000)


class FaultyDeployment(Fault):
    """inventory-service 2.4.0 ships a null-handling bug."""

    def setup(self, sim: Simulator) -> None:
        sim.version_changes.append((self.start_s, "inventory-service", "2.4.0"))
        sim.emit(
            self.start_s,
            "inventory-service",
            "info",
            "deployment",
            "deployment of inventory-service 2.4.0 completed (previous 2.3.1)",
            ground_truth=True,
            attributes={"previous_version": "2.3.1", "strategy": "rolling"},
        )

    def effect(self, sim: Simulator, target: str, operation: str, t: float) -> Effect | None:
        if target == "inventory-service" and t > self.start_s + 15 and sim.rng.random() < 0.4:
            return Effect(
                fail=True,
                status_code=500,
                error_type="NullPointerException",
                message="NullPointerException in ReservationMapper.toDto",
                event_type="exception",
            )
        return None


class RetryStorm(Fault):
    """A retry-policy change in orders-service turns a short inventory blip into a storm."""

    def setup(self, sim: Simulator) -> None:
        sim.policy_changes.append((self.start_s, (8, 0.0)))
        sim.emit(
            self.start_s,
            "orders-service",
            "info",
            "config_change",
            "retry policy for inventory-service updated: max_attempts 2 -> 8, backoff 250ms -> 0ms",
            ground_truth=True,
            attributes={"setting": "retry.inventory", "old": "2/250ms", "new": "8/0ms"},
        )
        sim.policy_changes.append((self.end_s, (2, 250.0)))
        sim.emit(
            self.end_s,
            "orders-service",
            "info",
            "config_change",
            "retry policy for inventory-service reverted: max_attempts 8 -> 2, "
            "backoff 0ms -> 250ms",
            attributes={"setting": "retry.inventory", "old": "8/0ms", "new": "2/250ms"},
        )
        # inventory-service sheds load above ~1.3x its normal 30-second request volume and
        # only recovers once load falls well below that (hysteresis, as a saturated queue).
        self.capacity = max(12, int(sim.config.rps * 0.75 * 30 * 1.3))
        self.overloaded = False

    def effect(self, sim: Simulator, target: str, operation: str, t: float) -> Effect | None:
        if target != "inventory-service":
            return None
        blip_start = self.start_s + 45
        if blip_start <= t < blip_start + 25:
            return Effect(extra_latency_ms=1500.0)
        if t < blip_start:
            return None
        load = sim.inventory_load(t, 30.0)
        if load > self.capacity:
            self.overloaded = True
        elif load < self.capacity * 0.6:
            self.overloaded = False
        if self.overloaded and sim.rng.random() < 0.9:
            return Effect(
                fail=True,
                status_code=503,
                error_type="Overloaded",
                message="load shedding: concurrency limit exceeded",
            )
        return None


class CacheFailure(Fault):
    """redis-cache is OOM-killed; reads fall back to inventory-db, which slows down."""

    def setup(self, sim: Simulator) -> None:
        sim.emit(
            self.start_s,
            "redis-cache",
            "critical",
            "log",
            "redis-server terminated: used_memory exceeded maxmemory (OOM)",
            ground_truth=True,
            error_type="OutOfMemory",
            attributes={"used_memory_mb": 8150, "maxmemory_mb": 8192},
        )
        sim.emit(
            self.end_s,
            "redis-cache",
            "info",
            "log",
            "redis-server restarted and ready",
            attributes={"used_memory_mb": 12},
        )

    def effect(self, sim: Simulator, target: str, operation: str, t: float) -> Effect | None:
        if target == "redis-cache":
            return Effect(
                fail=True,
                status_code=503,
                error_type="ConnectionRefusedError",
                message="connection refused (redis-cache:6379)",
            )
        if target == "inventory-db":
            ramp = min(1.0, (t - self.start_s) / 40.0)
            if operation == "SELECT items" and sim.rng.random() < 0.25 * ramp:
                sim.emit(
                    t,
                    "inventory-db",
                    "warning",
                    "log",
                    "slow query: SELECT * FROM items WHERE sku = $1 took >1000ms",
                    attributes={"active_queries": int(40 + 80 * ramp)},
                )
            return Effect(extra_latency_ms=ramp * (500 + sim.rng.random() * 1400))
        return None


class NetworkPartition(Fault):
    """Unobservable shared cause: two services fail at once with no linking evidence."""

    def effect(self, sim: Simulator, target: str, operation: str, t: float) -> Effect | None:
        if target in {"orders-service", "payments-service"} and sim.rng.random() < 0.6:
            return Effect(
                fail=True,
                status_code=503,
                error_type="ConnectionResetError",
                message="upstream request failed: connection reset",
            )
        return None


class BenignDeployment(Fault):
    """A deployment that does not change behaviour (noise for deployment heuristics)."""

    def setup(self, sim: Simulator) -> None:
        sim.version_changes.append((self.start_s, "payments-service", "1.8.4"))
        sim.emit(
            self.start_s,
            "payments-service",
            "info",
            "deployment",
            "deployment of payments-service 1.8.4 completed (previous 1.8.3)",
            attributes={"previous_version": "1.8.3", "strategy": "rolling"},
        )


class BackgroundNoise(Fault):
    """Scattered, unrelated warnings and errors across services."""

    MESSAGES = (
        ("warning", "GC pause of {n}ms exceeded 100ms target", None),
        ("warning", "request queue depth {n} above soft limit", None),
        (
            "error",
            "failed to publish metrics batch: broker unavailable ({n} items dropped)",
            "MetricsPublishError",
        ),
        ("error", "invalid coupon code rejected by validator (code length {n})", "ValidationError"),
        ("warning", "certificate for internal endpoint expires in {n} days", None),
    )

    def setup(self, sim: Simulator) -> None:
        t = sim.rng.uniform(5, 30)
        services = (
            "web-frontend",
            "api-gateway",
            "orders-service",
            "payments-service",
            "inventory-service",
        )
        while t < sim.config.duration_s:
            severity, template, error_type = sim.rng.choice(self.MESSAGES)
            sim.emit(
                t,
                sim.rng.choice(services),
                severity,
                "log",
                template.format(n=sim.rng.randint(5, 400)),
                error_type=error_type,
            )
            t += sim.rng.uniform(8, 40)


# ---------------------------------------------------------------- scenarios
@dataclass(frozen=True)
class ScenarioSpec:
    name: str
    title: str
    description: str
    expected_outcome: str  # "root_cause" | "no_incident" | "insufficient_evidence"
    root_cause_service: str | None
    fault_factory: Callable[[float, float], list[Fault]]
    config_overrides: dict[str, Any]


SCENARIOS: dict[str, ScenarioSpec] = {
    spec.name: spec
    for spec in (
        ScenarioSpec(
            "db-connection-exhaustion",
            "Database connection exhaustion",
            "orders-db reaches max_connections; orders-service connection-pool requests time "
            "out and checkout/order-status calls fail upstream.",
            "root_cause",
            "orders-db",
            lambda s, e: [DatabaseConnectionExhaustion(s, e)],
            {},
        ),
        ScenarioSpec(
            "downstream-api-timeout",
            "Downstream API timeout",
            "The external payment-provider (which emits no logs) slows down and then exceeds "
            "the 3s client timeout; payments-service and the gateway return errors.",
            "root_cause",
            "payment-provider",
            lambda s, e: [DownstreamTimeout(s, e)],
            {},
        ),
        ScenarioSpec(
            "faulty-deployment",
            "Faulty deployment",
            "inventory-service 2.4.0 is rolled out and ~40% of its requests throw "
            "NullPointerException; errors propagate to orders-service and the gateway.",
            "root_cause",
            "inventory-service",
            lambda s, e: [FaultyDeployment(s, e)],
            {},
        ),
        ScenarioSpec(
            "retry-storm",
            "Retry storm",
            "orders-service changes its retry policy to 8 attempts without backoff. A short "
            "inventory-service latency blip triggers retries that overload inventory-service "
            "until the policy is reverted.",
            "root_cause",
            "orders-service",
            lambda s, e: [RetryStorm(s, e)],
            {},
        ),
        ScenarioSpec(
            "cache-failure",
            "Cache failure with database load",
            "redis-cache is OOM-killed. inventory-service falls back to inventory-db, which "
            "slows down and starts timing out under the extra load.",
            "root_cause",
            "redis-cache",
            lambda s, e: [CacheFailure(s, e)],
            {},
        ),
        ScenarioSpec(
            "healthy-control",
            "Healthy control execution",
            "Normal traffic with a realistic background rate of transient errors. No incident "
            "was injected.",
            "no_incident",
            None,
            lambda s, e: [],
            {},
        ),
        ScenarioSpec(
            "ambiguous-partition",
            "Ambiguous incident with insufficient evidence",
            "orders-service and payments-service fail simultaneously because of a network "
            "partition that is not itself logged. Tracing is disabled, so no event links the "
            "failures to a cause. The correct answer is 'insufficient evidence'.",
            "insufficient_evidence",
            None,
            lambda s, e: [NetworkPartition(s, e)],
            {"tracing_enabled": False},
        ),
        ScenarioSpec(
            "unrelated-noise",
            "Unrelated noise",
            "Healthy traffic plus scattered unrelated warnings and errors, a higher transient "
            "error rate and a deployment that changes nothing. No incident was injected.",
            "no_incident",
            None,
            lambda s, e: [BackgroundNoise(s, e), BenignDeployment(s, e)],
            {"noise_error_rate": 0.01},
        ),
    )
}


def _variation(seed: int) -> dict[str, float]:
    """Seed-dependent traffic and fault timing (used for benchmark diversity)."""
    import random

    rng = random.Random(seed * 7919)
    duration = rng.uniform(480, 720)
    fault_start = duration * rng.uniform(0.35, 0.5)
    fault_end = fault_start + duration * rng.uniform(0.25, 0.4)
    return {
        "duration_s": round(duration, 1),
        "rps": round(rng.uniform(0.55, 0.95), 3),
        "noise_error_rate": round(rng.uniform(0.001, 0.004), 4),
        "fault_start_s": round(fault_start, 1),
        "fault_end_s": round(min(fault_end, duration - 30), 1),
        "day_offset": rng.randint(0, 200),
    }


def generate_scenario(name: str, seed: int, *, vary: bool = False) -> GeneratedScenario:
    """Generate one scenario.

    With ``vary=False`` (demo datasets) the timing is fixed: 600 s of traffic starting at
    2026-03-14 09:00 UTC with the fault active from 240 s to 450 s. With ``vary=True``
    (benchmarks) duration, traffic rate, noise and fault timing are derived from the seed.
    """
    spec = SCENARIOS[name]
    if vary:
        params = _variation(seed)
        start = DEMO_START + timedelta(days=params["day_offset"])
        config = SimConfig(
            seed=seed,
            start=start,
            duration_s=params["duration_s"],
            rps=params["rps"],
            noise_error_rate=params["noise_error_rate"],
        )
        window = ScenarioWindow(params["fault_start_s"], params["fault_end_s"])
    else:
        config = SimConfig(seed=seed, start=DEMO_START)
        window = ScenarioWindow(240.0, 450.0)
    overrides = dict(spec.config_overrides)
    if "noise_error_rate" in overrides and vary:
        overrides["noise_error_rate"] = max(overrides["noise_error_rate"], config.noise_error_rate)
    config = replace(config, **overrides)

    sim = Simulator(config, spec.fault_factory(window.start_s, window.end_s))
    raw = sim.run()

    events: list[dict[str, Any]] = []
    fault_event_ids: list[str] = []
    prefix = hashlib.sha1(f"{name}:{seed}".encode(), usedforsecurity=False).hexdigest()[:6]
    for index, record in enumerate(raw, start=1):
        event_id = f"ev-{prefix}-{index:05d}"
        if record.pop("_gt"):
            fault_event_ids.append(event_id)
        record.pop("_t")
        events.append({"event_id": event_id, **record})

    ground_truth = {
        "scenario": name,
        "title": spec.title,
        "seed": seed,
        "varied": vary,
        "expected_outcome": spec.expected_outcome,
        "root_cause_service": spec.root_cause_service,
        "fault_window": None
        if spec.expected_outcome == "no_incident"
        else {
            "start": sim.ts(window.start_s),
            "end": sim.ts(window.end_s),
        },
        "fault_event_ids": fault_event_ids,
        "description": spec.description,
        "event_count": len(events),
    }
    return GeneratedScenario(name=name, events=events, ground_truth=ground_truth)
