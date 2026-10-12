"""FastAPI application factory."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.migrations import upgrade_to_head
from app.core.security import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.static import mount_frontend
from app.services.imports import purge_expired_imports

logger = logging.getLogger("ghosttrace")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        app.state.startup_error = None
        try:
            if settings.auto_migrate:
                upgrade_to_head(settings.database_url)
            with app.state.database.session_factory() as session:
                purged = purge_expired_imports(session, settings)
            if purged:
                logger.info("Retention cleanup removed %d expired imports", purged)
        except Exception as exc:
            # Keep serving so /ready can report the failure instead of crash-looping.
            logger.exception("Startup initialisation failed")
            app.state.startup_error = f"initialisation failed: {type(exc).__name__}"
        yield
        app.state.database.dispose()

    app = FastAPI(
        title="GhostTrace API",
        version=__version__,
        description=(
            "Explainable incident reconstruction: import application events, correlate them, "
            "and review evidence-backed root-cause hypotheses."
        ),
        lifespan=lifespan,
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url="/redoc" if settings.enable_docs else None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
    )
    app.state.settings = settings
    app.state.database = Database(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Content-Disposition"],
    )

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        valid = 0 < len(incoming) <= 64 and incoming.isalnum()
        request_id = incoming if valid else uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # Outermost first: headers on every response, then size and rate limits.
    app.add_middleware(
        RateLimitMiddleware,
        per_minute=settings.rate_limit_per_minute,
        trust_proxy_headers=settings.trust_proxy_headers,
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_upload_bytes + 1024 * 1024)
    app.add_middleware(SecurityHeadersMiddleware)

    register_error_handlers(app)
    app.include_router(api_router)
    if settings.static_dir is not None:
        mount_frontend(app, settings.static_dir)
    return app


app = create_app()
