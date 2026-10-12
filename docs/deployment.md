# Deployment guide

GhostTrace ships as **one container**: FastAPI serves the API at `/api/v1` and the built React app on the same origin, so it needs no CORS configuration and one web service is enough. See [ADR 0005](adr/0005-single-container-deployment.md).

## 1. Verify locally first

```powershell
docker build -t ghosttrace:local .
docker run --rm -p 8000:8000 ghosttrace:local
# in another terminal
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready          # status: ready
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/datasets/demo/faulty-deployment/import
Start-Process http://127.0.0.1:8000
```

Tested on Docker Desktop 29.7 (Windows 11, WSL 2). The image is about 300 MB and used about 80 MiB of RAM after importing and analysing a demo dataset.

To run against PostgreSQL instead of SQLite:

```powershell
docker compose --profile postgres up --build postgres app-postgres   # http://localhost:8001
docker compose --profile postgres down -v                            # stop and delete its data
```

## 2. Render (free web service): recommended for a demo

What the free plan provides (checked October 2026; confirm on Render's pricing page before relying on it):

* Docker web services with 512 MB RAM and 0.1 CPU.
* The service **sleeps after about 15 minutes without traffic**. The first request afterwards waits roughly a minute while it wakes.
* The filesystem is **ephemeral**: the SQLite database resets on every restart, redeploy or sleep. That suits a demo, where visitors import the bundled datasets. For persistence, point `GHOSTTRACE_DATABASE_URL` at a managed PostgreSQL database.
* 750 free instance hours per workspace per month.

Steps (they need your Render account; nothing here has been run on your behalf):

1. Push the repository to GitHub (see `git-workflow/README.md`, kept outside this repository).
2. In Render, choose **New → Blueprint**, select the repository, and Render reads [`render.yaml`](../render.yaml).
3. Wait for the build, then open `https://<service>.onrender.com/api/v1/ready`.
4. Run the live demo check:

   ```powershell
   $base = "https://<service>.onrender.com/api/v1"
   Invoke-RestMethod "$base/ready"
   $imp = Invoke-RestMethod -Method Post "$base/datasets/demo/cache-failure/import"
   $inc = (Invoke-RestMethod "$base/incidents?import_id=$($imp.id)").items[0]
   $inc.top_service   # expected: redis-cache
   Invoke-RestMethod -Method Post -ContentType "application/json" -Body '{"format":"markdown"}' "$base/incidents/$($inc.id)/reports"
   ```

`render.yaml` sets a 12-hour retention, 30 mutating requests per minute, a 5 MiB upload cap, `TRUST_PROXY_HEADERS=true` (Render runs a proxy in front of the service) and leaves AI explanations off.

## 3. Railway (alternative)

Railway currently offers a 30-day trial with $5 of credit, then a Free plan with $1/month of usage on a 0.5 GB instance; Hobby is $5/month (checked October 2026). [`railway.json`](../railway.json) selects the Dockerfile builder and the readiness health check.

```powershell
railway login                 # opens a browser; uses your account
railway init                  # create a project (or `railway link` to an existing one)
railway up                    # builds the Dockerfile and deploys
railway variable set GHOSTTRACE_TRUST_PROXY_HEADERS=true GHOSTTRACE_RETENTION_HOURS=12
railway domain                # generate a public URL
```

Railway injects `$PORT`, which the image honours. Add a volume mounted at `/data` if you want SQLite to survive redeploys.

## 4. Hosting the frontend separately (optional)

When the API and frontend are on different origins, for example the static app on Netlify or GitHub Pages and the API on Render:

1. Build with the API URL: `$env:VITE_API_BASE_URL="https://api.example.com"; npm run build` in `frontend/`.
2. Configure the static host to serve `index.html` for unknown paths, so client-side routes work on reload.
3. Set `GHOSTTRACE_CORS_ORIGINS=https://your-frontend.example` on the API.

## Environment variables

See [`.env.example`](../.env.example) for every setting and its default. Never commit real secrets; set them in the hosting provider's dashboard.

## Operations checklist

* Health: `/api/v1/health` (liveness) and `/api/v1/ready` (DB reachable and schema at head; 503 otherwise).
* Logs: uvicorn access logs, plus application errors with request IDs that match the `X-Request-ID` response header.
* Upgrades: migrations run automatically at startup (`GHOSTTRACE_AUTO_MIGRATE=true`). If a migration fails, `/ready` reports it rather than the process crash-looping.
* Scaling: run a single worker with SQLite. For more than one replica, use PostgreSQL and an edge rate limiter, because the built-in limiter is per process.
