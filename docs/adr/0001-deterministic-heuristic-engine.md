# ADR 0001: A deterministic, explainable heuristic engine instead of a learned model

**Status:** accepted

## Context

The goal is to reconstruct incidents and suggest root causes in a way a human can audit. The project must run on an 8 GB laptop without a GPU or paid APIs. No labelled corpus of real incidents is available.

## Decision

Use documented, deterministic algorithms:

* Poisson burst tests for anomaly detection.
* Trace and dependency-call correlation.
* Graph analysis.
* A weighted-signal ranking with explicit contradiction penalties.

Every score breaks down into named signal values that cite event IDs.

## Consequences

* Results are reproducible and easy to test. Each hypothesis explains itself.
* Scores are uncalibrated heuristics and are labelled as such everywhere.
* The heuristics encode the author's domain assumptions, and they were developed alongside synthetic scenarios. The benchmark documents this leakage risk and uses held-out seeds plus a stress configuration that was not used for tuning.
* A learned model could later sit behind the same `rank_hypotheses` interface if labelled data became available.
