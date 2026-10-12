"""Generate one synthetic scenario as a JSONL file (ground truth goes to a separate file).

Usage::

    backend\\.venv\\Scripts\\python.exe scripts\\generate_scenario.py --scenario cache-failure \\
        --seed 3001 --out cache.jsonl [--truth cache.truth.json] [--vary]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.simulation import SCENARIOS, generate_scenario  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate one synthetic incident scenario.")
    parser.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--truth", type=Path, help="optional path for the ground-truth JSON")
    parser.add_argument("--vary", action="store_true", help="seed-dependent timing and traffic")
    args = parser.parse_args()

    generated = generate_scenario(args.scenario, args.seed, vary=args.vary)
    args.out.write_text(generated.to_jsonl(), encoding="utf-8", newline="\n")
    if args.truth:
        args.truth.write_text(json.dumps(generated.ground_truth, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(generated.events)} events to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
