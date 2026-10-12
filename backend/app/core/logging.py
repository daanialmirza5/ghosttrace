"""Logging configuration."""

from __future__ import annotations

import logging


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Uvicorn's access log already records requests; keep library noise down.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
