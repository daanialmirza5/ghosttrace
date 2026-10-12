"""Bundled demo datasets.

Only ``datasets/demo/catalog.json`` and the files it lists are exposed. The catalog holds
symptom-level summaries; ground-truth labels live in ``datasets/ground-truth`` and are never
read by the API or the analysis engine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.errors import NotFoundError
from app.schemas.imports import DemoDatasetOut


@dataclass(frozen=True)
class DemoDataset:
    info: DemoDatasetOut
    path: Path


def _catalog(directory: Path) -> list[dict[str, Any]]:
    catalog_path = directory / "catalog.json"
    if not catalog_path.is_file():
        return []
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    entries = data.get("datasets", [])
    return entries if isinstance(entries, list) else []


def list_demo_datasets(directory: Path) -> list[DemoDataset]:
    datasets: list[DemoDataset] = []
    root = directory.resolve()
    for entry in _catalog(directory):
        path = (root / str(entry.get("filename", ""))).resolve()
        # Refuse anything that escapes the demo directory.
        if path.parent != root or not path.is_file():
            continue
        datasets.append(
            DemoDataset(
                info=DemoDatasetOut(
                    name=entry["name"],
                    title=entry["title"],
                    summary=entry["summary"],
                    filename=path.name,
                    format=entry["format"],
                    size_bytes=path.stat().st_size,
                    field_mapping=entry.get("field_mapping"),
                ),
                path=path,
            )
        )
    return datasets


def get_demo_dataset(directory: Path, name: str) -> DemoDataset:
    for dataset in list_demo_datasets(directory):
        if dataset.info.name == name:
            return dataset
    raise NotFoundError(f"Demo dataset {name!r} does not exist.")
