"""Version 1 API router."""

from fastapi import APIRouter

from app.api.v1 import (
    comparisons,
    dashboard,
    explanations,
    health,
    imports,
    incidents,
    reports,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(imports.router)
api_router.include_router(incidents.router)
api_router.include_router(comparisons.router)
api_router.include_router(reports.router)
api_router.include_router(explanations.router)
api_router.include_router(dashboard.router)
