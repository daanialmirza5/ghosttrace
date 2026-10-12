# Event formats

GhostTrace accepts UTF-8 text in any of three formats. A leading byte-order mark is allowed.

| Format | Detection | Error positions |
| --- | --- | --- |
| **JSON Lines** (`.jsonl`, `.ndjson`, `.log`) | One JSON object per line; blank lines are skipped | line number |
| **JSON document** (`.json`) | An array of events, or an envelope `{"events": [...], ...}` | 1-based record index |
| **CSV** (`.csv`) | A header row followed by data rows; optional field mapping | file line number |

Set `format` explicitly (`jsonl`, `json` or `csv`) if auto-detection guesses wrong.

## Canonical fields

| Field | Required | Type | Accepted aliases (case-insensitive) |
| --- | --- | --- | --- |
| `event_id` | no (derived from content if missing) | string ≤ 128 | `id`, `eventId`, `uuid`, `log_id` |
| `timestamp` | **yes** | ISO 8601, or Unix s / ms / µs | `ts`, `time`, `@timestamp`, `datetime`, `date`, `event_time` |
| `service` | **yes** | `[A-Za-z0-9][A-Za-z0-9._:/@-]*` | `service_name`, `serviceName`, `service.name`, `app`, `application`, `component` |
| `severity` | **yes** | debug, info, warning, error, critical | `level`, `log_level`, `loglevel`, `lvl`, `severity_text` |
| `event_type` | no (default `log`) | see below | `type`, `eventType`, `kind`, `category` |
| `message` | no | string ≤ 8192 | `msg`, `log`, `text`, `body` |
| `environment` | no (default `unknown`) | string | `env`, `deployment_environment` |
| `trace_id`, `span_id`, `parent_span_id` | no | string | `traceId`, `trace.id`, `trace`; `spanId`; `parent_id`, `parentSpanId` |
| `request_id` | no | string | `correlation_id`, `correlationId`, `x_request_id` |
| `deployment_version` | no | string | `version`, `release`, `service_version`, `build` |
| `duration_ms` | no | number ≥ 0 | `latency_ms`, `latencyMs`, `elapsed_ms` |
| `status_code` | no | integer 100-599 | `http_status`, `statusCode`, `http.status_code` (not `status`, which is usually free text) |
| `target_service` | no | service name | `peer_service`, `peer.service`, `downstream`, `dependency` |
| `error_type` | no | string | `exception_type`, `errorType`, `error_kind`, `error.type` |
| `attributes` | no | object of scalars | `attrs`, `fields`, `context`, `extra`; unknown top-level fields are added here too |

**Severity aliases.** `trace` maps to debug. `notice` and `information` map to info. `warn` maps to warning. `err` maps to error. `crit`, `fatal`, `alert`, `emerg` and `panic` map to critical.

**Event types.** `log`, `request`, `span`, `dependency_call`, `exception`, `timeout`, `retry`, `deployment`, `config_change`, `metric`, `healthcheck`. Accepted aliases: `http`/`http_request` → request, `dependency`/`client_call`/`outbound` → dependency_call, `error` → exception, `deploy`/`release` → deployment, `config` → config_change, `health` → healthcheck.

## What each field enables

* `trace_id`, `span_id` and `parent_span_id` let GhostTrace find dependency edges, propagation and the origin of a failing trace.
* `target_service` on `dependency_call`, `timeout` or `retry` events records calls to datastores or external APIs that emit no logs of their own (shown as *inferred* services).
* `duration_ms` drives latency signals. On outbound calls the latency is attributed to the callee.
* `deployment` / `config_change` events and `deployment_version` drive change proximity and regression detection. A version flip with no deployment event becomes an implicit change point.

Without traces or `target_service`, GhostTrace can still detect anomalies. It will usually report **insufficient evidence** for the root cause, which is the honest answer in that case.

## Examples

```json
{"event_id":"e1","timestamp":"2026-03-14T09:04:00.120Z","service":"orders-service","severity":"error","event_type":"dependency_call","message":"INSERT orders on orders-db failed: QueuePool limit reached","trace_id":"4bf9…","span_id":"a1","parent_span_id":"a0","target_service":"orders-db","duration_ms":1950,"error_type":"PoolTimeoutError"}
{"id":"e2","ts":1773479040,"app":"inventory-service","level":"INFO","type":"deploy","msg":"deployed 2.4.0","version":"2.4.0","attributes":{"previous_version":"2.3.1"}}
```

A CSV file with non-canonical headers, imported with a field mapping:

```csv
time,svc,level,text,latency
2026-03-14T09:00:00Z,api-gateway,warn,slow upstream,1234
```

```json
{"time": "timestamp", "svc": "service", "level": "severity", "text": "message", "latency": "duration_ms"}
```

A mapping target can also be `attributes.<name>`. Columns not in the mapping are still matched against the aliases above; anything unrecognised becomes an attribute.

## Validation and limits

* Rejected records are listed with position, field and reason (the first `GHOSTTRACE_MAX_REPORTED_ERRORS`, default 200). The rest of the file is still imported.
* An event ID that repeats with **identical** content is skipped and counted as a duplicate. An event ID that repeats with **different** content is rejected.
* Duplicates are detected within one import only. Separate imports are separate datasets.
* Default limits: 10 MiB per upload, 50,000 records, 64 KiB per line, 64 attributes per event. A file over the record limit fails as a whole rather than being silently truncated.
* Content is only decoded with `json` and `csv` from the Python standard library. It is never evaluated or executed. Deeply nested JSON is rejected safely.
