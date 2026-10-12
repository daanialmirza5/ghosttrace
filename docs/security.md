# Security and privacy

GhostTrace is a portfolio and demo application. It has **no authentication or authorisation**: anyone who can reach the API can import, read and delete data. Do not expose it to the internet with real or sensitive logs unless an authenticating reverse proxy sits in front of it. The project makes no claim of compliance with any security standard or certification.

## What is implemented

| Area | Measure | Where |
| --- | --- | --- |
| Upload handling | Size limit enforced on `Content-Length` and while streaming chunked bodies (413). The file is read into memory, never written to disk or executed. Only the normalised events are stored. | `core/security.py`, `api/v1/imports.py` |
| Parsing | Standard-library `json`/`csv` only. Line-length, record-count and attribute limits. Deep nesting is caught. Invalid UTF-8 is rejected. | `services/ingestion/parsers.py` |
| Input validation | Pydantic schemas on every request; strict canonical event schema; field-mapping validation | `schemas/` |
| Untrusted log text | Escaped in Markdown reports (no links, images, HTML or table breaks). Rendered as text in React (no `dangerouslySetInnerHTML`). Never used as instructions. | `services/reporting/report.py` |
| Rate limiting | Sliding window per client for POST/PUT/PATCH/DELETE (default 60/min, 429 + `Retry-After`). Uses `X-Forwarded-For` only when `GHOSTTRACE_TRUST_PROXY_HEADERS=true`. | `core/security.py` |
| CORS | Explicit origin allow-list, no credentials, limited methods and headers | `main.py` |
| Response headers | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cross-Origin-Resource-Policy: same-site`, a strict CSP on the API and a same-origin CSP on the app | `core/security.py` |
| Error responses | A generic message and request ID for unexpected errors; stack traces only in server logs | `core/errors.py` |
| Database | SQLAlchemy parameterised queries; `LIKE` wildcards escaped; one transaction per import | `repositories/` |
| Secrets | Environment variables only. The `SecretStr` AI key is never logged or returned by `/settings`. `.env` is git-ignored. | `core/config.py` |
| Retention | Imports older than `GHOSTTRACE_RETENTION_HOURS` (default 24) are deleted at startup and at most every 10 minutes after imports. Imports can also be deleted manually. | `services/imports.py` |
| Container | Non-root user, no build tools in the runtime image, healthcheck, memory limit in compose | `Dockerfile`, `docker-compose.yml` |
| Supply chain | Exact version pins: `requirements*.txt` are fully pinned with `uv pip compile` (without hashes), and `package-lock.json` pins the frontend. CI runs `pip-audit` and `npm audit --audit-level=high`. | `.github/workflows/ci.yml` |

## Optional AI provider

* Off by default (`GHOSTTRACE_AI_PROVIDER=none`), and every feature works without it.
* When enabled, the provider receives **only** GhostTrace-computed facts: service names, signal descriptions, scores and event IDs. Raw log messages are sent only if `GHOSTTRACE_AI_SEND_EVENT_MESSAGES=true`, and then inside a delimited block the model is told to treat as untrusted data.
* Output must match a JSON schema and is re-validated. Any cited event ID outside the incident's evidence set causes the answer to be discarded in favour of the deterministic template. Timeouts and a bounded number of retries are configurable.
* Results are always labelled "AI-generated interpretation" or "Deterministic template".
* Sending data to an external provider means that data leaves your machine under that provider's terms. Review this before enabling it with real logs.

## Not covered (known gaps)

* No user accounts, API keys, roles or multi-tenancy.
* The rate limiter is per process and in memory. It is not shared across replicas and resets on restart.
* No encryption at rest. SQLite files and PostgreSQL volumes are as safe as the host they sit on.
* No virus or malware scanning of uploads (they are parsed as text and never executed or served back).
* Interactive `/docs` loads Swagger UI assets from a CDN and is exempt from the app CSP. Disable it with `GHOSTTRACE_ENABLE_DOCS=false` if that matters.
* Analysis runs synchronously, so a large valid upload occupies a worker for several seconds. Body and record limits bound this, but they are not a full denial-of-service defence.

## Reporting a vulnerability

Please open a private security advisory on the GitHub repository rather than a public issue.
