"""Smoke test: the benchmark harness grades runs correctly (one seed, fast)."""

from __future__ import annotations

import importlib.util
import json

from app.core.config import REPO_DIR

spec = importlib.util.spec_from_file_location(
    "run_benchmark", REPO_DIR / "benchmarks" / "run_benchmark.py"
)
assert spec and spec.loader
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def test_fault_run_is_graded() -> None:
    result = bench.run_one("faulty-deployment", 2001, "standard")
    assert result["detected"] is True
    assert result["top1_correct"] is True
    assert result["analysis_ms"] > 0


def test_control_and_ambiguous_runs_are_graded() -> None:
    assert bench.run_one("healthy-control", 2001, "standard")["false_positive"] is False
    assert bench.run_one("ambiguous-partition", 2001, "standard")["abstained"] is True


def test_malformed_injection_is_counted_exactly() -> None:
    check = bench.ingestion_check("cache-failure", 2001)
    assert check["injected_malformed"] > 0
    assert check["classified_correctly"] is True


def test_corruption_is_deterministic() -> None:
    lines = [json.dumps({"service": "a", "severity": "info", "timestamp": i}) for i in range(200)]
    assert bench.corrupt(lines, 7) == bench.corrupt(lines, 7)
