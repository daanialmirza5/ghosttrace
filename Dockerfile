# GhostTrace all-in-one image: FastAPI serves the API and the built React app on one port.

# ---- Frontend build ----------------------------------------------------------------
FROM node:22.20.0-alpine3.22 AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Runtime ---------------------------------------------------------------------------
FROM python:3.12.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GHOSTTRACE_ENVIRONMENT=production \
    GHOSTTRACE_DATABASE_URL=sqlite:////data/ghosttrace.db \
    GHOSTTRACE_STATIC_DIR=/app/static \
    GHOSTTRACE_DEMO_DATASETS_DIR=/app/datasets/demo \
    PORT=8000

RUN groupadd --system ghost && useradd --system --gid ghost --home /app ghost
WORKDIR /app/backend
ARG INSTALL_POSTGRES=0
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt \
 && if [ "$INSTALL_POSTGRES" = "1" ]; then pip install "psycopg[binary]==3.3.6"; fi
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY datasets/demo /app/datasets/demo
COPY --from=frontend /build/dist /app/static
RUN rm -rf app/tests && mkdir -p /data && chown -R ghost:ghost /data

USER ghost
EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/v1/ready', timeout=4)"
# Hosting platforms inject $PORT; one worker keeps memory low (~120 MB) and SQLite safe.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
