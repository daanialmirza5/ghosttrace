# How GhostTrace analyses events

Every step is deterministic: the same events always produce the same signals, incidents, hypotheses and replay frames. The code locations below are in `backend/app/services`.

## 1. Normalisation (`normalization/normalizer.py`)

Each record becomes a `CanonicalEvent` (`schemas/events.py`). Field names are matched case-insensitively against documented aliases. The record is **rejected** with its line number and the offending field when:

* the timestamp is not ISO 8601 or a Unix epoch (s/ms/µs), or its year falls outside 2000-2100;
* the severity or event type is not in the documented vocabulary (values are never guessed);
* two aliases of the same field disagree, for example `severity: error` and `level: info`;
* a typed field cannot be parsed (`duration_ms: "fast"`, `status_code: 200.5`);
* the service name contains characters outside `[A-Za-z0-9._:/@-]`;
* there are more than 64 attributes, or the line is longer than 64 KiB.

Values that *are* accepted but changed are reported as warnings in the import summary, never silently:

| Warning | Meaning |
| --- | --- |
| `naive_timestamp_assumed_utc` | an ISO timestamp without an offset was interpreted as UTC |
| `event_id_derived` | the record had no ID, so `gt-<sha256 prefix of the raw record>` was used |
| `attributes_serialised` | a nested list or object attribute was stored as a compact JSON string |
| `duplicate_skipped` | an identical record with the same ID was skipped |

A record whose ID repeats with **different** content is rejected rather than merged.

## 2. Correlation (`correlation/engine.py`)

| Rule | Creates |
| --- | --- |
| Events share a `trace_id`; a span's `parent_span_id` matches a span of another service | call edge `parent → child` (evidence: the child span event) |
| `dependency_call` / `timeout` / `retry` event with `target_service` | call edge `service → target` (the target may be an *inferred* service that emits no events) |
| Events share a `request_id` but have no trace | related-event group (no edge) |
| Child span error, then a parent span error at the same time or later | propagation `child → parent` |
| Failed dependency call | propagation `target → caller` |
| **Events that are only close in time** | **nothing.** Timing never creates an edge or a causal link. |

For each failing trace, the *origin* is the deepest erroring span (one with no erroring child). If that span contains a failed outbound call, the origin is the call's target. Errors whose span has an erroring child are marked *explained downstream*.

## 3. Incident detection (`incident_detection/detector.py`)

Counts are bucketed with a width of `clamp(span / 40, 10 s, 60 s)`. A **burst** is a 60-second sliding window whose count is

* at least the signal's minimum count, **and**
* improbable under a Poisson model of the baseline: P(X ≥ k) < 1e-4, where the baseline rate is the mean of the quietest 75% of buckets (floor 0.05 per bucket).

| Signal | Basis | Series | Extra conditions |
| --- | --- | --- | --- |
| `error_spike` | observed | errors per service | ≥ 6 errors, ≥ 10% of the service's events in the window |
| `repeated_exception` | observed | errors per (service, error_type) | ≥ 5 |
| `timeout_cluster` | observed | timeout events per (service, target) | ≥ 4 |
| `retry_storm` | observed | retry events per (service, target) | ≥ 8, retries ≥ 20% of calls to the target |
| `dependency_failure` | observed | failed calls per edge | ≥ 4, ≥ 25% of calls failed |
| `latency_increase` | observed | durations per *measured* service (outbound calls measure the callee) | window p90 or p50 ≥ max(2.5 × baseline, baseline + 250 ms); the baseline is the median across windows |
| `deployment_regression` | **inferred** | a deployment, config change or implicit version flip, followed by the service's own errors | ≥ 5 errors in the next 5 minutes; Poisson p < 1e-3 against the preceding rate |
| `cascading_failure` | **inferred** | propagation links between failing services | ≥ 3 propagations per link |
| `missing_trace_context` | observed (data quality) | orphan spans, untraced events | ≥ 10% orphan spans, or < 20% traced events |

Primary signals (error spike, latency, timeouts, retry storm, dependency failure) are grouped by time overlap, with a gap tolerance of max(60 s, 2 buckets), to form incidents. Secondary signals attach when they overlap. A regression attaches when its change happened up to 15 minutes before the incident. **Concurrent but unrelated problems therefore end up in one incident.** This is a deliberate simplification: it keeps ambiguous cases together so they can be flagged, rather than splitting them arbitrarily.

## 4. Service graph (`graph_analysis/graph.py`)

Nodes are observed services, plus *inferred* services that only appear as call targets. A node's health is the **worse** of (a) its own error rate and (b) the failure rate of calls made to it:

* `failing`: rate ≥ 20% and at least 5 failures;
* `degraded`: rate ≥ 5% with at least 3 failures, or rate ≥ 20% with at least 1;
* otherwise `healthy`, or `unknown` when there is no data.

Cycles are found with an iterative Tarjan SCC. Depth is the breadth-first distance from the entry points (nodes with no callers). Disconnected components are counted, never dropped.

## 5. Root-cause ranking (`root_cause/ranker.py`)

Candidates are the incident's services, any failing or degraded graph nodes, and any service with a change in the window. Each candidate gets six signal values in [0, 1]:

| Signal | Weight | Value |
| --- | ---: | --- |
| temporal_precedence | 0.20 | exp(−Δ/τ), where Δ is the time from the earliest candidate's onset to this candidate's onset. Onset is the first moment the service has ≥ 3 warning-or-worse events within 30 s (outbound-call events count for the callee). τ = max(30 s, window/8). |
| trace_origin | 0.20 | share of failing traces whose origin is this candidate |
| dependency_position | 0.15 | share of other affected services that can reach this candidate in the graph (they depend on it) |
| change_proximity | 0.15 | exp(−gap/600 s) for its latest change before its onset; × 0.4 if no regression followed |
| intrinsic_failure | 0.15 | max(share of its own errors not explained downstream × min(1, n/5), failure ratio of calls to it). Capped at 0.5 when tracing is absent. |
| retry_amplification | 0.15 | share of the incident's retries it emitted (only when it is the source of a retry storm) |

**Penalties** (contradictory evidence) are subtracted:

| Penalty | Amount | When |
| --- | ---: | --- |
| downstream_failed_first | 0.15 | its calls to a failing dependency failed ≥ 3 times, and that dependency's onset was no later than its own (+5 s). Skipped when the candidate is retry-storming that dependency. |
| overload_under_retry_storm | 0.20 | its own errors look like load shedding (429/503, "overload", "rate limit") while another service's retry storm targets it |
| errors_before_incident | 0.10 | its error rate in the 10 minutes before the incident was at least half its rate during it |

`score = clip(Σ weight × value − Σ penalties, 0, 1)`. Candidates are ordered by score, then onset, then name. **The score is an uncalibrated heuristic and is not a probability.** The API returns it with the label `"heuristic score (not a probability)"`.

### Evidence status and uncertainty

* `insufficient`: there is no structural evidence (≥ 3 failing traces, or an edge with ≥ 3 errors between candidates) **and** no change events, or the top score is below 0.30. The UI and reports then say that a root cause cannot be ranked, and recommend collecting tracing and dependency data.
* `ambiguous`: the top two scores are within 0.05 of each other.
* `sufficient`: otherwise. Even then the result is described as "the highest-ranked hypothesis", never as proven.

A hypothesis has *low* uncertainty only if it is ranked first, the evidence is sufficient, its score is ≥ 0.55, its margin is ≥ 0.15 and it has no contradictions. It has *high* uncertainty when the score is < 0.35 or the evidence is not sufficient. Otherwise it is *medium*.

Each hypothesis lists its signal contributions with evidence event IDs, contradictions, missing information (for example "emits no events; inferred from N calls", "no latency measurements", "no trace context") and a recommended next step. Before an incident is stored, every event ID it cites is checked against the import. The same check runs again before any report is produced.

## 6. Replay (`replay/engine.py`)

Frames are the incident window's events sorted by `(timestamp, event_id)`. After **every** event, service health is re-evaluated over the previous 30 seconds of simulated time:

* `failing`: ≥ 3 errors and an error ratio ≥ 20%;
* `degraded`: ≥ 1 error or ≥ 3 warnings;
* otherwise `healthy`.

Frames carry only the state changes. Filters hide events from playback but never from the state computation, so the state at any shown frame is identical with or without filters (this is tested). The UI caps idle gaps at 1.5 s of wall-clock time at the selected speed.

## 7. Comparison (`comparison/engine.py`)

Two executions are compared on per-minute event volume, error rate, p95 latency (only where both sides have measurements; otherwise the row is labelled "not measured"), versions, node status and dependency edges. A comparison is flagged as **not comparable** when either side has fewer than 20 events or less than 30 s of data, or when the service sets overlap with Jaccard similarity < 0.3. A difference of more than 3× in window length or more than 2× in traffic produces a warning.

## Known limitations

* The heuristics were developed alongside the synthetic scenarios (see [the benchmark README](../benchmarks/README.md)). They have not been validated on production telemetry.
* High background error rates raise false positives quickly (25% FPR in the `stress` benchmark configuration).
* Clock skew between services is not corrected, so temporal precedence can mislead when clocks drift by more than a few seconds.
* Sampled traces under-count calls, and the edge statistics do not correct for sampling.
* One incident can mix unrelated concurrent problems (see section 3).
* Analysis is synchronous and in-memory. A near-limit upload of about 21,000 events took about 2.8 s to ingest and analyse on the development laptop, before database writes. Per-record Pydantic validation is the dominant cost.
