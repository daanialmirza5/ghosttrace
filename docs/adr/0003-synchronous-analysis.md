# ADR 0003: Analyse imports synchronously inside the request

**Status:** accepted

## Context

A job queue (Celery or RQ, plus Redis) would add services, memory use and failure modes. The default limits are 10 MiB and 50,000 records per upload.

## Decision

Validate, persist and analyse inside the `POST /imports` request, in one database transaction. Analysis results are computed in memory first. Any cited event ID that doesn't exist raises an integrity error, and in that case the import is stored with `analysis_status = "failed"` rather than being lost.

## Consequences

* The client always gets the final result in the response, and there is no polling or eventual consistency to handle.
* Measured on the development laptop, a 9.9 MB upload of 21,000 events completes in about 5.5 s end to end, including analysis and SQLite writes. The request holds a worker for that long, and the upload and record limits bound it.
* If inputs grow, move `import_content` behind a background task. Its signature already isolates the work.
