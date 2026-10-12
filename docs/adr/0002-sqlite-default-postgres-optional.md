# ADR 0002: SQLite by default, PostgreSQL optional

**Status:** accepted

## Context

Setup has to be lightweight on Windows: no services running in the background and no Docker requirement for development. The project also needs a credible production database option.

## Decision

Use SQLAlchemy 2 with portable column types (JSON, timezone-aware datetimes through a `UTCDateTime` type decorator) and Alembic migrations. They are generated with `render_as_batch` so `ALTER TABLE` works on SQLite. SQLite runs in WAL mode with foreign keys on. PostgreSQL is selected with `GHOSTTRACE_DATABASE_URL` and the optional `psycopg[binary]` extra.

## Consequences

* Running `pip install` followed by `uvicorn` is enough to get a working app.
* PostgreSQL was verified end to end with the compose `postgres` profile: migrations, import, case-insensitive search, comparison, reports and cascading delete.
* SQLite limits concurrency to one writer. The container runs one worker. For multiple replicas, use PostgreSQL.
