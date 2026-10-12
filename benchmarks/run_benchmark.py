"""GhostTrace benchmark: detection, root-cause ranking, ingestion and performance.

Usage (from the repository root)::

    backend\\.venv\\Scripts\\python.exe benchmarks\\run_benchmark.py
    backend\\.venv\\Scripts\\python.exe benchmarks\\run_benchmark.py --seeds 2001-2003 --quick

Methodology (see benchmarks/README.md):

* Scenarios are generated with ``vary=True`` from **held-out seeds** (default 2001-2010).
  These seeds were never used while developing the heuristics (development used seed 42,
  seeds 7 and 11, and 1001-1008 for generator robustness checks).
* Three telemetry configurations: ``standard`` (97% of spans keep their parent link),
  ``degraded`` (80%) and ``stress`` (60% plus a 2% background error rate). ``stress`` was
  added after the first results and was not used for tuning.
* The engine only ever sees the generated event bytes. Ground truth is read afterwards,
  solely to grade the result.
* Wall-clock timings come from ``time.perf_counter``; memory is the ``tracemalloc`` peak of
  one ingest+analyse pass and only covers Python allocations.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.services.analysis import analyze  # noqa: E402
from app.services.ingestion import ingest_bytes  # noqa: E402
from app.simulation import SCENARIOS, generate_scenario  # noqa: E402

CONFIGS: dict[str, dict[str, Any]] = {
    "standard": {},
    "degraded": {"trace_coverage": 0.80},
    "stress": {"trace_coverage": 0.60, "noise_error_rate": 0.02},
}
FAULTS = [n for n, s in SCENARIOS.items() if s.expected_outcome == "root_cause"]


def parse_seeds(text: str) -> list[int]:
    seeds: list[int] = []
    for part in text.split(","):
        if "-" in part:
            low, high = part.split("-")
            seeds.extend(range(int(low), int(high) + 1))
        else:
            seeds.append(int(part))
    return seeds


def corrupt(lines: list[str], seed: int) -> tuple[list[str], int]:
    """Deterministically corrupt every 50th line in one of five documented ways."""
    out: list[str] = []
    corrupted = 0
    for index, line in enumerate(lines):
        if index % 50 != seed % 50:
            out.append(line)
            continue
        corrupted += 1
        record = json.loads(line)
        kind = (index // 50) % 5
        if kind == 0:
            out.append(line[: len(line) // 2])  # truncated JSON
        elif kind == 1:
            record["severity"] = "loud"
            out.append(json.dumps(record))
        elif kind == 2:
            record["timestamp"] = "not-a-time"
            out.append(json.dumps(record))
        elif kind == 3:
            record.pop("service")
            out.append(json.dumps(record))
        else:
            record["duration_ms"] = "fast"
            out.append(json.dumps(record))
    return out, corrupted


def overlaps(incident: Any, window: dict[str, str] | None) -> bool:
    if window is None:
        return False
    start = datetime.fromisoformat(window["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(window["end"].replace("Z", "+00:00"))
    return incident.draft.start <= end and incident.draft.end >= start


def run_one(name: str, seed: int, config: str) -> dict[str, Any]:
    generated = generate_scenario(name, seed, vary=True, config_overrides=CONFIGS[config])
    truth = generated.ground_truth
    content = generated.to_jsonl().encode()

    started = time.perf_counter()
    ingested = ingest_bytes(content, filename=f"{name}.jsonl")
    ingest_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    analysis = analyze(ingested.events)
    analysis_ms = (time.perf_counter() - started) * 1000

    expected = truth["expected_outcome"]
    matching = [i for i in analysis.incidents if overlaps(i, truth["fault_window"])]
    primary = max(matching, key=lambda i: i.draft.error_count) if matching else None
    hypotheses = primary.ranking.hypotheses if primary else []
    status = primary.ranking.evidence_status if primary else None
    services = [h.service for h in hypotheses]
    result: dict[str, Any] = {
        "scenario": name,
        "seed": seed,
        "config": config,
        "expected_outcome": expected,
        "root_cause": truth["root_cause_service"],
        "events": len(ingested.events),
        "rejected": ingested.summary.rejected,
        "incidents": len(analysis.incidents),
        "spurious_incidents": len(analysis.incidents) - len(matching),
        "detected": primary is not None,
        "evidence_status": status,
        "top3": services[:3],
        "top_score": hypotheses[0].score if hypotheses else None,
        "ingest_ms": round(ingest_ms, 2),
        "analysis_ms": round(analysis_ms, 2),
    }
    if expected == "root_cause":
        result["top1_correct"] = (
            bool(services)
            and services[0] == truth["root_cause_service"]
            and (status != "insufficient")
        )
        result["top3_hit"] = truth["root_cause_service"] in services[:3]
    elif expected == "insufficient_evidence":
        result["abstained"] = status == "insufficient"
    else:
        result["false_positive"] = len(analysis.incidents) > 0
    return result


def ingestion_check(name: str, seed: int) -> dict[str, Any]:
    generated = generate_scenario(name, seed, vary=True)
    lines = generated.to_jsonl().splitlines()
    corrupted_lines, corrupted = corrupt(lines, seed)
    summary = ingest_bytes("\n".join(corrupted_lines).encode(), filename="x.jsonl").summary
    valid = len(lines) - corrupted
    return {
        "scenario": name,
        "seed": seed,
        "records": len(lines),
        "valid_records": valid,
        "injected_malformed": corrupted,
        "accepted": summary.accepted,
        "rejected": summary.rejected,
        "classified_correctly": summary.accepted == valid and summary.rejected == corrupted,
    }


def memory_peak(name: str, seed: int) -> float:
    content = generate_scenario(name, seed, vary=True).to_jsonl().encode()
    tracemalloc.start()
    events = ingest_bytes(content, filename="x.jsonl").events
    analyze(events)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / (1024 * 1024)


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def rate(items: list[dict[str, Any]], key: str) -> float | None:
    return round(sum(1 for i in items if i[key]) / len(items), 4) if items else None


def summarise(runs: list[dict[str, Any]]) -> dict[str, Any]:
    faults = [r for r in runs if r["expected_outcome"] == "root_cause"]
    ambiguous = [r for r in runs if r["expected_outcome"] == "insufficient_evidence"]
    controls = [r for r in runs if r["expected_outcome"] == "no_incident"]
    return {
        "runs": len(runs),
        "fault_runs": len(faults),
        "detection_recall": rate(faults, "detected"),
        "top1_accuracy": rate(faults, "top1_correct"),
        "top3_recall": rate(faults, "top3_hit"),
        "insufficient_evidence_abstention_rate": rate(ambiguous, "abstained"),
        "control_runs": len(controls),
        "false_positive_rate": rate(controls, "false_positive"),
        "spurious_incidents_in_fault_runs": sum(r["spurious_incidents"] for r in faults),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the GhostTrace benchmark.")
    parser.add_argument("--seeds", default="2001-2010")
    parser.add_argument("--quick", action="store_true", help="standard config only")
    parser.add_argument("--output", default=str(REPO / "benchmarks" / "results" / "latest.json"))
    args = parser.parse_args()

    seeds = parse_seeds(args.seeds)
    configs = ["standard"] if args.quick else list(CONFIGS)
    started = time.perf_counter()
    runs = [
        run_one(name, seed, config) for config in configs for seed in seeds for name in SCENARIOS
    ]
    ingestion = [ingestion_check(name, seed) for seed in seeds for name in SCENARIOS]
    largest = max((r for r in runs if r["config"] == "standard"), key=lambda r: r["events"])
    peak_mb = memory_peak(largest["scenario"], largest["seed"])

    total_events = sum(r["events"] for r in runs)
    analysis = [r["analysis_ms"] for r in runs]
    ingest = [r["ingest_ms"] for r in runs]
    per_scenario = {}
    for config in configs:
        for name in SCENARIOS:
            subset = [r for r in runs if r["scenario"] == name and r["config"] == config]
            key = (
                "top1_correct"
                if name in FAULTS
                else (
                    "abstained"
                    if SCENARIOS[name].expected_outcome == "insufficient_evidence"
                    else "false_positive"
                )
            )
            per_scenario[f"{config}/{name}"] = {
                "runs": len(subset),
                "metric": key,
                "rate": rate(subset, key),
                "top3_recall": rate(subset, "top3_hit") if name in FAULTS else None,
                "misses": [
                    {
                        "seed": r["seed"],
                        "top3": r["top3"],
                        "status": r["evidence_status"],
                    }
                    for r in subset
                    if (key == "false_positive") == bool(r[key])
                ],
            }

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "seeds": seeds,
        "configs": {name: CONFIGS[name] for name in configs},
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
        },
        "summary": {
            config: summarise([r for r in runs if r["config"] == config]) for config in configs
        },
        "ingestion": {
            "records": sum(i["records"] for i in ingestion),
            "injected_malformed": sum(i["injected_malformed"] for i in ingestion),
            "valid_records": sum(i["valid_records"] for i in ingestion),
            "accepted": sum(i["accepted"] for i in ingestion),
            "success_rate": round(
                sum(i["accepted"] for i in ingestion) / sum(i["valid_records"] for i in ingestion),
                4,
            ),
            "files_classified_exactly": rate(ingestion, "classified_correctly"),
            "clean_runs_rejected_records": sum(r["rejected"] for r in runs),
        },
        "performance": {
            "total_events": total_events,
            "events_per_run_median": statistics.median(r["events"] for r in runs),
            "ingest_ms_p50": round(pct(ingest, 0.5), 1),
            "ingest_ms_p95": round(pct(ingest, 0.95), 1),
            "analysis_ms_p50": round(pct(analysis, 0.5), 1),
            "analysis_ms_p95": round(pct(analysis, 0.95), 1),
            "analysis_ms_max": round(max(analysis), 1),
            "events_per_second_end_to_end": round(
                total_events / ((sum(analysis) + sum(ingest)) / 1000), 0
            ),
            "tracemalloc_peak_mb_largest_run": round(peak_mb, 1),
            "largest_run_events": largest["events"],
        },
        "per_scenario": per_scenario,
        "wall_clock_seconds": round(time.perf_counter() - started, 1),
        "runs": runs,
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")

    print(f"seeds {args.seeds}, configs {configs}, {len(runs)} runs, {total_events} events")
    for config, summary in report["summary"].items():
        print(
            f"[{config}] detection {summary['detection_recall']:.0%}  "
            f"top-1 {summary['top1_accuracy']:.0%}  top-3 {summary['top3_recall']:.0%}  "
            f"abstention {summary['insufficient_evidence_abstention_rate']:.0%}  "
            f"FPR {summary['false_positive_rate']:.0%}  "
            f"spurious {summary['spurious_incidents_in_fault_runs']}"
        )
    perf = report["performance"]
    print(
        f"ingestion success {report['ingestion']['success_rate']:.2%}, files exact "
        f"{report['ingestion']['files_classified_exactly']:.0%}; analysis p50 "
        f"{perf['analysis_ms_p50']} ms p95 {perf['analysis_ms_p95']} ms; peak "
        f"{perf['tracemalloc_peak_mb_largest_run']} MB"
    )
    for key, row in per_scenario.items():
        if row["misses"]:
            print(f"  {key}: {row['metric']}={row['rate']} misses={row['misses']}")
    print(f"wrote {output.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
