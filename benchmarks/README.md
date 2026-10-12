# GhostTrace benchmark

`run_benchmark.py` measures detection, root-cause ranking, ingestion and performance on
synthetic incidents produced by the deterministic simulator in
`backend/app/simulation/`. Raw results for every run are in
[`results/latest.json`](results/latest.json).

```powershell
# from the repository root (about 2 minutes on a 4-core laptop)
backend\.venv\Scripts\python.exe benchmarks\run_benchmark.py
# faster smoke run
backend\.venv\Scripts\python.exe benchmarks\run_benchmark.py --seeds 2001-2002 --quick
```

## What is measured

| Metric | Definition |
| --- | --- |
| Detection recall | Fault runs where at least one incident overlaps the injected fault window. |
| Top-1 accuracy | Fault runs where the highest-ranked hypothesis of the main overlapping incident is the ground-truth service **and** the engine did not declare the evidence insufficient. |
| Top-3 recall | Fault runs where the ground-truth service is among the first three hypotheses. |
| Abstention rate | Runs of the ambiguous scenario where the engine reports `insufficient` evidence (the correct answer there). |
| False-positive rate | Control runs (healthy and unrelated-noise) that produced one or more incidents. |
| Spurious incidents | Incidents in fault runs that do not overlap the fault window. |
| Ingestion success rate | Accepted records divided by valid records, after injecting malformed lines (every 50th line: truncated JSON, unknown severity, bad timestamp, missing service, non-numeric duration). "Files exact" means accepted and rejected counts both matched exactly. |
| Latency | `time.perf_counter` around ingestion (parse, validate, deduplicate) and around analysis (correlate, detect, graph, rank). Database writes and HTTP overhead are not included. |
| Memory | `tracemalloc` peak during one ingest and analyse pass of the largest run. It counts Python allocations only, not total process RSS. |

## Test conditions

* **Seeds:** 2001-2010, held out. While developing the heuristics I used seed 42 (the demo datasets), seeds 7 and 11, and seeds 1001-1008 to check the generator was robust. Seeds 2001-2010 were not looked at before the first benchmark run.
* **Variation per seed:** duration of 8 to 12 minutes, 0.55 to 0.95 requests per second, a background transient-error rate of 0.1 to 0.4%, and fault onset and length all drawn from the seed.
* **Configurations:**
  * `standard`: 97% of spans keep their parent link.
  * `degraded`: 80% of spans keep their parent link.
  * `stress`: 60% of spans keep their parent link, and the background error rate is 2%. I added `stress` after seeing the first results and did not change any heuristics afterwards.
* **Size:** 8 scenarios × 10 seeds × 3 configurations = 240 runs and 577,081 events, with a median of 2,376 events per run.
* **Machine:** Windows 11, Intel Core (4 logical CPUs), Python 3.12.14, on a laptop with other applications running. Wall clock was 180 s. On the same machine an earlier, less loaded run measured about 40% lower latencies, so treat the latency figures as order-of-magnitude only.

## Results (2026-10-10, from `results/latest.json`)

| Configuration | Detection recall | Top-1 | Top-3 | Abstention (ambiguous) | False-positive rate | Spurious incidents |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| standard | 100% (50/50) | 100% | 100% | 100% (10/10) | 0% (0/20) | 0 |
| degraded | 100% (50/50) | 100% | 100% | 100% (10/10) | 0% (0/20) | 0 |
| stress | 100% (50/50) | 94% (47/50) | 100% | 100% (10/10) | **25% (5/20)** | 0 |

Failures under `stress`:

* **Retry storm, seed 2002:** the incident was classed as *ambiguous*. `inventory-service` and `orders-service` scored nearly the same, so this counts as a top-1 miss.
* **Cache failure, seeds 2003 and 2004:** both were *ambiguous*, with `orders-service` slightly ahead of `redis-cache`. The ground truth was still in the top 3.
* **Controls:** healthy seeds 2007 and 2008, and unrelated-noise seeds 2002, 2007 and 2008, each produced an incident. At a 2% per-span error rate, errors that propagate up from four services give the entry service bursts the Poisson test treats as significant.

| Ingestion | Value |
| --- | --- |
| Records (with injected malformed lines) | 191,821 |
| Injected malformed | 3,869, all rejected |
| Valid records accepted | 187,952 of 187,952 (100%) |
| Files with exact accepted/rejected counts | 80 of 80 |

| Performance | Value |
| --- | --- |
| Ingestion p50 / p95 | 342 ms / 614 ms per run |
| Analysis p50 / p95 / max | 85 ms / 171 ms / 303 ms per run |
| End-to-end throughput (ingest + analyse) | about 5,400 events/s |
| tracemalloc peak (largest run, 3,362 events) | 9.4 MB |

**Change history.** The first benchmark run scored 98% top-1 under `stress`. Later, while reviewing the UI, I changed one graph rule: a service's health is now the *worse* of its own error rate and the failure rate of calls made to it (previously only its own events counted). The dependency-position signal depends on node health, so this changed rankings and `stress` top-1 fell to 94%. I did not tune anything to recover the lost points.

## How to read these numbers (limitations and leakage risks)

* **The perfect scores on `standard` and `degraded` are not evidence of real-world accuracy.** The same person designed the simulator and the heuristics, and each scenario represents a failure mechanism the heuristics were built to recognise. Varying seeds tests robustness to timing, volume and noise. It does not test unfamiliar failure modes.
* **One heuristic is tied directly to one scenario.** The `overload_under_retry_storm` penalty encodes a domain rule ("a service shedding load while being hit by a retry storm is likely a victim"). It is reasonable in general, but it was written while looking at the retry-storm scenario.
* **Ground truth never reaches the engine.** The engine receives only event bytes, `datasets/ground-truth` is read only by tests and this script, and `test_ground_truth_is_not_embedded_in_events` checks that no label fields appear in events. Labels can still leak *indirectly*, through design choices like the one above.
* **There is one topology**, an 8-service e-commerce system. Larger or differently shaped systems have not been evaluated.
* **The scores are heuristic.** "Top-1 accuracy" measures ranking only. Scores are uncalibrated and are not probabilities.
* **Real telemetry is messier.** It has clock skew, sampling, multi-tenant noise and inconsistent schemas, and none of these are modelled. The `stress` configuration shows false positives rising quickly as background noise increases.
