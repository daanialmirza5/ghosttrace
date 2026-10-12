# Troubleshooting

### "An Application Control policy has blocked this file" when running `uvicorn`, `pytest` or `alembic`

Some Windows machines block the `.exe` launchers that pip creates inside a virtual environment. Run the module through the venv's Python instead. Every command in this repository's docs is written that way:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m alembic upgrade head
```

### `Activate.ps1 cannot be loaded because running scripts is disabled`

You don't need to activate the venv; call `.\.venv\Scripts\python.exe` directly. If you prefer activation, allow it for the current session only: `Set-ExecutionPolicy -Scope Process RemoteSigned`.

### The UI says "Could not reach the GhostTrace API"

* Check that the backend is running: `Invoke-RestMethod http://127.0.0.1:8000/api/v1/health`.
* The Vite dev server proxies `/api` to `http://127.0.0.1:8000`. If the backend runs on another port, set `$env:GHOSTTRACE_API_PROXY="http://127.0.0.1:<port>"` before `npm run dev`.
* If the frontend is hosted on a different origin, set `VITE_API_BASE_URL` when building and add that origin to `GHOSTTRACE_CORS_ORIGINS`.

### `/api/v1/ready` returns 503

The response lists the failing check:

* `startup: initialisation failed` means migrations failed at startup. Look for the traceback in the server log.
* `database: unreachable` means `GHOSTTRACE_DATABASE_URL` is wrong or the database is down.
* `schema: migrations pending` means `GHOSTTRACE_AUTO_MIGRATE=false` was set without running `python -m alembic upgrade head`.

### Port already in use (`[Errno 10048]` or "Bind for 0.0.0.0:8000 failed")

Another process or container holds the port. Find it with `Get-NetTCPConnection -LocalPort 8000 -State Listen` (and `docker ps` for containers), then pick another port: `--port 8010` for uvicorn, `$env:GHOSTTRACE_PORT=8010` for compose.

### An import shows `failed`

Open it in the import workspace. `file_error` gives the reason: invalid UTF-8, unparseable JSON document, more than `GHOSTTRACE_MAX_RECORDS_PER_IMPORT` records, a field mapping on a non-CSV file, or zero valid records. Per-record problems are listed with line numbers instead, and they do not fail the import.

### An incident says "insufficient evidence"

This is a deliberate result, not a bug. It means the affected services are not linked by traces, `target_service` calls or change events. Add trace context (`trace_id`, `span_id`, `parent_span_id`) or `target_service` on outbound calls, plus deployment events, and import again.

### Upload rejected with 413

The default limit is 10 MiB (`GHOSTTRACE_MAX_UPLOAD_BYTES`); the Render blueprint uses 5 MiB. Split the file, or raise the limit if the host has enough memory.

### 429 "Too many requests"

The built-in limiter allows 60 mutating requests per minute per client. Set `GHOSTTRACE_RATE_LIMIT_PER_MINUTE=0` to disable it locally.

### Playwright tests can't find a browser

The config uses the locally installed Microsoft Edge (`channel: msedge`). To use Playwright's bundled Chromium instead: `npx playwright install chromium`, then `$env:PW_CHANNEL="bundled"`.

### Docker Desktop is slow, or uses a lot of memory on 8 GB machines

GhostTrace's container uses about 80 MiB. Starting Docker Desktop also restarts any other project's containers that have a restart policy, so check `docker ps` and stop what you don't need. Stop Docker Desktop entirely with `docker desktop stop`.

## Cleaning up

```powershell
Remove-Item -Recurse -Force backend\.venv, backend\data, frontend\node_modules, frontend\dist -ErrorAction SilentlyContinue
docker image rm ghosttrace:local ghosttrace:local-postgres   # if you built the images
docker volume rm ghosttrace_ghosttrace-data                   # compose SQLite volume
```
