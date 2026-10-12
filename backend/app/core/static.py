"""Optional serving of the built frontend (single-container deployments).

When ``GHOSTTRACE_STATIC_DIR`` points at a Vite ``dist`` directory, files are served from
it and any other non-API path returns ``index.html`` so client-side routes work on reload.
API, docs and OpenAPI paths are never shadowed.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response

RESERVED_PREFIXES = ("/api/", "/docs", "/redoc", "/openapi.json")


def mount_frontend(app: FastAPI, directory: Path) -> None:
    root = directory.resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(f"GHOSTTRACE_STATIC_DIR={directory} does not contain index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str, request: Request) -> Response:
        path = request.url.path
        if path.startswith(RESERVED_PREFIXES) or path == "/api":
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_file() and root in candidate.parents:
            # Hashed build assets can be cached for a long time; index.html must not be.
            cache = "public, max-age=31536000, immutable" if "/assets/" in path else "no-cache"
            return FileResponse(candidate, headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
