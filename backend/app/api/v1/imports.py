"""Import endpoints: upload files, load demo datasets, inspect imported events."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.api.deps import DatabaseDep, SessionDep, SettingsDep
from app.core.errors import PayloadTooLargeError, UnprocessableError
from app.core.timeutil import as_utc
from app.repositories import imports as import_repo
from app.repositories.imports import EventFilter
from app.schemas.common import Page
from app.schemas.events import EventOut, EventType, Severity
from app.schemas.imports import DemoDatasetOut, ImportOut, ImportStatus
from app.services import demo_datasets
from app.services.imports import import_content

router = APIRouter(tags=["imports"])

FormatParam = Literal["auto", "jsonl", "json", "csv"]
_READ_CHUNK = 1024 * 1024


async def _read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(_READ_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLargeError(
                f"File exceeds the {max_bytes // (1024 * 1024)} MiB upload limit."
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_mapping(raw: str | None) -> dict[str, str] | None:
    if raw is None or not raw.strip():
        return None
    try:
        mapping = json.loads(raw)
    except ValueError as exc:
        raise UnprocessableError("field_mapping must be a JSON object.") from exc
    if not isinstance(mapping, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in mapping.items()
    ):
        raise UnprocessableError("field_mapping must map column names to field names.")
    if len(mapping) > 100:
        raise UnprocessableError("field_mapping may contain at most 100 entries.")
    return mapping


@router.post("/imports", response_model=ImportOut, status_code=status.HTTP_201_CREATED)
async def create_import(
    database: DatabaseDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="JSONL, JSON array/envelope, or CSV")],
    name: Annotated[str | None, Form(max_length=200)] = None,
    format: Annotated[FormatParam, Form()] = "auto",
    field_mapping: Annotated[
        str | None, Form(description='CSV only: JSON object {"column": "canonical_field"}')
    ] = None,
) -> ImportOut:
    """Upload and validate an event file.

    The response always describes the stored import. Files that could not be parsed are
    stored with ``status="failed"`` and a ``file_error``; per-record problems are listed in
    ``errors``. Only transport problems (size, missing file) produce 4xx responses.
    """
    mapping = _parse_mapping(field_mapping)
    content = await _read_limited(file, settings.max_upload_bytes)
    filename = (file.filename or "upload")[:255]

    def work() -> ImportOut:
        with database.session_factory() as session:
            record = import_content(
                session,
                settings,
                content=content,
                filename=filename,
                name=name,
                declared_format=None if format == "auto" else format,
                field_mapping=mapping,
            )
            return ImportOut.from_record(record)

    return await run_in_threadpool(work)


@router.get("/datasets/demo", response_model=list[DemoDatasetOut])
def list_demo(settings: SettingsDep) -> list[DemoDatasetOut]:
    """Bundled synthetic datasets that can be imported with one request."""
    return [
        dataset.info for dataset in demo_datasets.list_demo_datasets(settings.demo_datasets_dir)
    ]


@router.post(
    "/datasets/demo/{name}/import", response_model=ImportOut, status_code=status.HTTP_201_CREATED
)
def import_demo(name: str, session: SessionDep, settings: SettingsDep) -> ImportOut:
    dataset = demo_datasets.get_demo_dataset(settings.demo_datasets_dir, name)
    content = dataset.path.read_bytes()
    record = import_content(
        session,
        settings,
        content=content,
        filename=dataset.info.filename,
        name=dataset.info.title,
        declared_format=dataset.info.format,
        field_mapping=dataset.info.field_mapping,
        demo_dataset=dataset.info.name,
    )
    return ImportOut.from_record(record)


@router.get("/imports", response_model=Page[ImportOut])
def list_imports(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[ImportStatus | None, Query(alias="status")] = None,
) -> Page[ImportOut]:
    items, total = import_repo.list_imports(
        session, limit=limit, offset=offset, status=status_filter
    )
    return Page(
        items=[ImportOut.from_record(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/imports/{import_id}", response_model=ImportOut)
def get_import(import_id: str, session: SessionDep) -> ImportOut:
    return ImportOut.from_record(import_repo.get_import(session, import_id))


@router.delete("/imports/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_import(import_id: str, session: SessionDep) -> Response:
    with session.begin():
        import_repo.delete_import(session, import_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/imports/{import_id}/events", response_model=Page[EventOut])
def list_events(
    import_id: str,
    session: SessionDep,
    start: datetime | None = None,
    end: datetime | None = None,
    service: Annotated[list[str] | None, Query()] = None,
    severity: Annotated[list[Severity] | None, Query()] = None,
    event_type: Annotated[list[EventType] | None, Query()] = None,
    trace_id: Annotated[str | None, Query(max_length=128)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[EventOut]:
    import_repo.get_import(session, import_id)
    flt = EventFilter(
        start=as_utc(start),
        end=as_utc(end),
        services=tuple(service or ()),
        severities=tuple(item.value for item in severity or ()),
        event_types=tuple(item.value for item in event_type or ()),
        trace_id=trace_id,
        search=q,
    )
    items, total = import_repo.query_events(session, import_id, flt, limit=limit, offset=offset)
    return Page(
        items=[EventOut.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
