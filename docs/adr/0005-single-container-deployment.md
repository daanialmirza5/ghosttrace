# ADR 0005: One container serves the API and the SPA

**Status:** accepted

## Context

Free hosting tiers usually allow one small web service (Render: 512 MB, sleeps when idle). Development laptops have 8 GB of RAM. Separate frontend and API origins would need CORS configuration and two deployments.

## Decision

A multi-stage Dockerfile builds the Vite app and copies `dist/` into the Python image. When `GHOSTTRACE_STATIC_DIR` is set, FastAPI serves:

* hashed assets with long-lived caching;
* `index.html` for every other non-API path, so client-side routes work on reload.

The SPA route never shadows `/api`, `/docs` or `/openapi.json`. The app pages get a same-origin CSP.

## Consequences

* One image, one port and one origin: the image is about 300 MB and used about 80 MiB of RAM in testing.
* Hosting the frontend separately remains possible through `VITE_API_BASE_URL` and `GHOSTTRACE_CORS_ORIGINS`.
* Python serves the static files. That's fine at demo scale; put a CDN in front for heavier traffic.
