"""ORM models. Import every model here so Alembic autogenerate can discover it."""

from app.models.base import Base

__all__ = ["Base"]
