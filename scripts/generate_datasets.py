"""Generate (or verify) the bundled demo datasets.

Usage (from the repository root)::

    backend\\.venv\\Scripts\\python.exe scripts\\generate_datasets.py           # regenerate
    backend\\.venv\\Scripts\\python.exe scripts\\generate_datasets.py --verify  # check hashes

Outputs:
    datasets/demo/<scenario>.jsonl      events only (what users import)
    datasets/demo/faulty-deployment.csv the same scenario as CSV with non-canonical headers
    datasets/demo/malformed-sample.jsonl a small file that exercises validation errors
    datasets/ground-truth/<scenario>.json labels, used only by tests and benchmarks
    datasets/MANIFEST.json              SHA-256 of every generated file
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.simulation import SCENARIOS, generate_scenario  # noqa: E402

DEMO_SEED = 42
DEMO_DIR = REPO / "datasets" / "demo"
TRUTH_DIR = REPO / "datasets" / "ground-truth"
MANIFEST = REPO / "datasets" / "MANIFEST.json"

CSV_COLUMNS = {
    "id": "event_id",
    "time": "timestamp",
    "svc": "service",
    "env": "environment",
    "level": "severity",
    "kind": "event_type",
    "text": "message",
    "trace": "trace_id",
    "span": "span_id",
    "parent": "parent_span_id",
    "req": "request_id",
    "build_version": "deployment_version",
    "latency": "duration_ms",
    "http_code": "status_code",
    "peer": "target_service",
    "error": "error_type",
}

# Symptom-level descriptions shown in the UI. They intentionally do not reveal the answer.
CATALOG = {
    "db-connection-exhaustion": (
        "Checkout and order lookups failing",
        "Order requests start timing out and failing mid-morning.",
    ),
    "downstream-api-timeout": (
        "Payments timing out",
        "Checkout latency climbs and payments begin to fail.",
    ),
    "faulty-deployment": (
        "Errors after a release",
        "Browse and checkout errors appear during a normal release window.",
    ),
    "retry-storm": (
        "Inventory overload",
        "Inventory requests are rejected under heavy load.",
    ),
    "cache-failure": (
        "Slow product pages",
        "Product pages slow down and some requests fail.",
    ),
    "healthy-control": ("Normal traffic (control)", "Ten minutes of ordinary traffic."),
    "ambiguous-partition": (
        "Simultaneous failures, no tracing",
        "Two services fail at once in a system without tracing.",
    ),
    "unrelated-noise": (
        "Noisy but healthy",
        "Scattered warnings, errors and one deployment.",
    ),
}

MALFORMED_LINES = [
    '{"event_id":"m-1","timestamp":"2026-03-14T09:00:00Z","service":"api-gateway",'
    '"severity":"info","message":"valid record"}',
    '{"event_id":"m-2","timestamp":"2026-03-14T09:00:01Z","service":"api-gateway",'
    '"severity":"error","message":"valid error","error_type":"Boom"}',
    '{"event_id":"m-3","timestamp":"2026-03-14T09:00:02Z","service":"api-gateway"',
    '{"event_id":"m-4","timestamp":"not a time","service":"api-gateway","severity":"info"}',
    '{"event_id":"m-5","timestamp":"2026-03-14T09:00:04Z","severity":"info","message":"x"}',
    '{"event_id":"m-6","timestamp":"2026-03-14T09:00:05Z","service":"api-gateway",'
    '"severity":"loud"}',
    '["an","array","is","not","an","event"]',
    '{"event_id":"m-1","timestamp":"2026-03-14T09:00:00Z","service":"api-gateway",'
    '"severity":"info","message":"valid record"}',
    '{"event_id":"m-2","timestamp":"2026-03-14T09:00:09Z","service":"orders-service",'
    '"severity":"info","message":"same id, different content"}',
    '{"event_id":"m-10","timestamp":"2026-03-14T09:00:10Z","service":"api-gateway",'
    '"severity":"info","duration_ms":"fast"}',
    '{"event_id":"m-11","timestamp":"2026-03-14 09:00:11","service":"api-gateway",'
    '"severity":"warn","message":"naive timestamp is accepted as UTC with a warning"}',
    '{"event_id":"m-12","timestamp":1773478812000,"service":"api-gateway",'
    '"level":"info","msg":"epoch milliseconds and aliases"}',
    '{"event_id":"m-13","ts":"2026-03-14T09:00:13Z","service":"api-gateway",'
    '"severity":"info","level":"error"}',
    "",
    '{"event_id":"m-14","timestamp":"2026-03-14T09:00:14Z","service":"api gateway!",'
    '"severity":"info"}',
]
MALFORMED_EXPECTED = {
    "records": 14,  # blank lines are skipped and not counted
    "accepted": 4,  # m-1, m-2, m-11, m-12
    "duplicates": 1,  # second m-1 (identical content)
    "rejected": 9,
}


def _csv_text(events: list[dict[str, object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for event in events:
        writer.writerow(
            ["" if event.get(field) is None else event[field] for field in CSV_COLUMNS.values()]
        )
    return buffer.getvalue()


def build_files() -> dict[Path, str]:
    files: dict[Path, str] = {}
    for name in SCENARIOS:
        scenario = generate_scenario(name, DEMO_SEED)
        files[DEMO_DIR / f"{name}.jsonl"] = scenario.to_jsonl()
        files[TRUTH_DIR / f"{name}.json"] = json.dumps(scenario.ground_truth, indent=2) + "\n"
        if name == "faulty-deployment":
            files[DEMO_DIR / "faulty-deployment.csv"] = _csv_text(scenario.events)
            files[TRUTH_DIR / "faulty-deployment.csv.json"] = (
                json.dumps(
                    {**scenario.ground_truth, "csv_field_mapping": CSV_COLUMNS},
                    indent=2,
                )
                + "\n"
            )
    files[DEMO_DIR / "malformed-sample.jsonl"] = "\n".join(MALFORMED_LINES) + "\n"
    catalog = [
        {
            "name": name,
            "title": title,
            "summary": summary,
            "filename": f"{name}.jsonl",
            "format": "jsonl",
        }
        for name, (title, summary) in CATALOG.items()
    ]
    catalog.append(
        {
            "name": "faulty-deployment-csv",
            "title": "Errors after a release (CSV)",
            "summary": "The release-window dataset as CSV with non-canonical column names, "
            "imported through a field mapping.",
            "filename": "faulty-deployment.csv",
            "format": "csv",
            "field_mapping": CSV_COLUMNS,
        }
    )
    catalog.append(
        {
            "name": "malformed-sample",
            "title": "Malformed records sample",
            "summary": "Fifteen lines exercising validation: bad JSON, unknown severities, "
            "duplicates, conflicting fields.",
            "filename": "malformed-sample.jsonl",
            "format": "jsonl",
        }
    )
    files[DEMO_DIR / "catalog.json"] = json.dumps({"datasets": catalog}, indent=2) + "\n"
    files[TRUTH_DIR / "malformed-sample.json"] = (
        json.dumps(
            {"scenario": "malformed-sample", "expected_import": MALFORMED_EXPECTED},
            indent=2,
        )
        + "\n"
    )
    return files


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--verify",
        action="store_true",
        help="regenerate in memory and compare with files on disk",
    )
    args = parser.parse_args()

    files = build_files()
    manifest = {
        "seed": DEMO_SEED,
        "files": {
            path.relative_to(REPO).as_posix(): sha256(text) for path, text in sorted(files.items())
        },
    }

    if args.verify:
        problems = 0
        recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]
        for relative, digest in manifest["files"].items():
            path = REPO / relative
            on_disk = sha256(path.read_text(encoding="utf-8")) if path.exists() else None
            if on_disk != digest or recorded.get(relative) != digest:
                problems += 1
                print(f"MISMATCH {relative}")
        print(
            "OK: all datasets match the generator" if not problems else f"{problems} file(s) differ"
        )
        return 1 if problems else 0

    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    total = sum(len(text.encode("utf-8")) for text in files.values())
    print(f"wrote {len(files)} files ({total / 1024:.0f} KiB) and {MANIFEST.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
