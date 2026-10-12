# ADR 0004: Store incidents, recompute timelines, graphs and replays

**Status:** accepted

## Context

Incident detection and ranking are the expensive, decision-bearing outputs. Timelines, graphs and replays are views over the same events.

## Decision

Persist incidents, including signals, hypotheses and missing information, as JSON at import time. Recompute timelines, graphs and replay frames from the stored events on every request, using deterministic ordering by `(timestamp, event_id)`.

## Consequences

* A view can never disagree with the events it shows, and the views need no cache-invalidation logic.
* Each request does `O(window events)` of work: a few hundred milliseconds for the demo datasets.
* Replay identity (`replay_id`) is a hash of the incident, the filters and the ordered event IDs, so identical requests always return the same frames.
