# REST API (v1)

Interactive OpenAPI documentation is served at `/docs` (Swagger UI) and `/redoc`, and the schema at `/openapi.json`, while the backend is running. Set `GHOSTTRACE_ENABLE_DOCS=false` to turn them off. All endpoints are under `/api/v1`.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness: the process is serving requests |
| `GET` | `/ready` | Readiness: startup succeeded, the DB answers, the schema is at the Alembic head. Returns **503** otherwise |
| `POST` | `/imports` | Upload a file (multipart: `file`, optional `name`, `format` = auto\|jsonl\|json\|csv, `field_mapping` JSON for CSV) |
| `GET` | `/imports` | Paginated imports (`limit`, `offset`, `status`) |
| `GET` | `/imports/{import_id}` | Import summary: counts, line-level errors, warnings, analysis status |
| `DELETE` | `/imports/{import_id}` | Delete an import and its events, incidents, reports and comparisons |
| `GET` | `/imports/{import_id}/events` | Events with filters: `start`, `end`, `service`*, `severity`*, `event_type`*, `trace_id`, `q` (message/ID search), `limit` ≤ 500, `offset` |
| `GET` | `/imports/{import_id}/graph` | Service graph for the whole import |
| `GET` | `/datasets/demo` | Bundled synthetic datasets (symptom-level descriptions only) |
| `POST` | `/datasets/demo/{name}/import` | Import a bundled dataset |
| `GET` | `/incidents` | Paginated incidents (`import_id`, `severity`, `evidence_status`) |
| `GET` | `/incidents/{incident_id}` | Detail: signals, ranked hypotheses, missing information, data quality |
| `GET` | `/incidents/{incident_id}/hypotheses` | Hypotheses plus the scoring method (weights and penalties) |
| `GET` | `/incidents/{incident_id}/timeline` | Window events with `service`*, `severity`*, `category`*, `event_type`*, `start`, `end`, `evidence_only`, `limit` ≤ 2000, `offset`; markers; 60-bucket histogram |
| `GET` | `/incidents/{incident_id}/graph` | Service graph of the incident window, with hypothesis ranks on nodes |
| `GET` | `/incidents/{incident_id}/events/{event_id}` | One event, the events in the same trace or request, and the signals and hypotheses citing it |
| `POST` | `/incidents/{incident_id}/replay` | Deterministic replay frames. Body: `services`, `severities`, `categories`, `max_frames` ≤ 5000 |
| `POST` | `/incidents/{incident_id}/explanations` | Narrative explanation: AI if configured, otherwise a deterministic template (always labelled) |
| `POST` | `/incidents/{incident_id}/reports` | Generate a report. Body: `format` = markdown\|json, optional `comparison_id` |
| `GET` | `/incidents/{incident_id}/reports` | Reports for an incident (metadata only) |
| `GET` | `/reports/{report_id}` | A report, including its content |
| `GET` | `/reports/{report_id}/download` | Download as an attachment |
| `POST` | `/comparisons` | Compare `baseline` and `target`, each `{import_id, incident_id? or start?/end?, label?}` |
| `GET` | `/comparisons` | Recent comparisons |
| `GET` | `/comparisons/{comparison_id}` | One comparison |
| `GET` | `/dashboard/summary` | Counts and recent items computed from stored data |
| `GET` | `/settings` | Effective non-secret configuration |

\* repeatable query parameter, for example `?service=a&service=b`.

## Errors

Every error uses the same shape, and each response carries an `X-Request-ID` header:

```json
{ "error": { "code": "not_found", "message": "Import 'imp_x' was not found.", "request_id": "3f2c…" } }
```

| Status | `code` | When |
| --- | --- | --- |
| 404 | `not_found` | Unknown resource or route |
| 413 | `payload_too_large` | Upload over `GHOSTTRACE_MAX_UPLOAD_BYTES` (checked while streaming) |
| 422 | `validation_error` | Request parameters or body fail schema validation (`details` lists the fields) |
| 422 | `unprocessable` | Well-formed but unusable request (bad field mapping, replay too large, mismatched IDs) |
| 429 | `rate_limited` | Too many mutating requests; see the `Retry-After` header |
| 500 | `internal_error` | Unexpected error. No stack trace or internal detail is returned; use the request ID to find it in the logs |

A file that can be uploaded but not parsed is **not** an HTTP error. It is stored as an import with `status: "failed"` and a `file_error`, so failed uploads remain visible in the import history.

## Example session (PowerShell)

```powershell
$api = "http://127.0.0.1:8000/api/v1"
$import = Invoke-RestMethod -Method Post "$api/datasets/demo/faulty-deployment/import"
$incident = (Invoke-RestMethod "$api/incidents?import_id=$($import.id)").items[0]
(Invoke-RestMethod "$api/incidents/$($incident.id)/hypotheses").hypotheses |
  Select-Object rank, service, score, uncertainty
$report = Invoke-RestMethod -Method Post -ContentType "application/json" `
  -Body '{"format":"markdown"}' "$api/incidents/$($incident.id)/reports"
Invoke-WebRequest "http://127.0.0.1:8000$($report.download_url)" -OutFile incident.md
```

Upload a file with curl:

```powershell
curl.exe -F "file=@datasets/demo/cache-failure.jsonl" http://127.0.0.1:8000/api/v1/imports
```
