"""Datasets: named collections of inputs to evaluate against."""

import dataclasses
import datetime
import json
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from ..core.models import new_id, utcnow
from ..storage.duckdb_store import Store


@dataclasses.dataclass
class DatasetItem:
    id: str
    input: Dict[str, Any]
    expected_output: Any = None
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)
    dataset_id: Optional[str] = None


@dataclasses.dataclass
class Dataset:
    id: str
    name: str
    description: Optional[str]
    created_at: datetime.datetime


def create(
    store: Store,
    name: str,
    items: Iterable[dict],
    description: Optional[str] = None,
) -> Dataset:
    """Create a dataset from dicts of ``{input, expected_output, metadata}``."""
    existing = get(store, name)
    if existing is not None:
        raise ValueError(f"a dataset named {name!r} already exists")

    dataset = Dataset(id=new_id(), name=name, description=description, created_at=utcnow())
    store.upsert(
        "datasets",
        [
            {
                "id": dataset.id,
                "name": dataset.name,
                "description": dataset.description,
                "created_at": dataset.created_at,
            }
        ],
    )
    store.upsert(
        "dataset_items",
        [
            {
                "id": item.id,
                "dataset_id": dataset.id,
                "input": item.input,
                "expected_output": item.expected_output,
                "metadata": item.metadata,
                "created_at": dataset.created_at,
            }
            for item in (_item(raw, dataset.id) for raw in items)
        ],
    )
    return dataset


def get(store: Store, name: str) -> Optional[Dataset]:
    row = store.db.execute(
        "SELECT id, name, description, created_at FROM datasets WHERE name = ?", [name]
    ).fetchone()
    return Dataset(*row) if row else None


def items(store: Store, dataset_id: str) -> List[DatasetItem]:
    rows = store.db.execute(
        """
        SELECT id, input, expected_output, metadata
        FROM dataset_items WHERE dataset_id = ? ORDER BY id
        """,
        [dataset_id],
    ).fetchall()
    return [
        DatasetItem(
            id=identifier,
            input=json.loads(raw_input),
            expected_output=json.loads(expected) if expected is not None else None,
            metadata=json.loads(metadata) if metadata else {},
            dataset_id=dataset_id,
        )
        for identifier, raw_input, expected, metadata in rows
    ]


def listing(store: Store) -> List[dict]:
    rows = store.db.execute(
        """
        SELECT d.name, d.description, count(i.id) AS items, d.created_at
        FROM datasets d
        LEFT JOIN dataset_items i ON i.dataset_id = d.id
        GROUP BY ALL
        ORDER BY d.created_at DESC
        """
    ).fetchall()
    return [
        dict(zip(("name", "description", "items", "created_at"), row)) for row in rows
    ]


def resolve(
    store: Store, dataset: Union[str, Dataset, Sequence[dict]]
) -> Tuple[Optional[Dataset], List[DatasetItem]]:
    """Accept a dataset name, a Dataset, or a list of raw dicts for a one-off run."""
    if isinstance(dataset, Dataset):
        return dataset, items(store, dataset.id)
    if isinstance(dataset, str):
        found = get(store, dataset)
        if found is None:
            raise LookupError(
                f"no dataset named {dataset!r}. Create one with evalforge.eval.dataset.create()."
            )
        return found, items(store, found.id)
    return None, [_item(raw, None) for raw in dataset]


def _item(raw: Any, dataset_id: Optional[str]) -> DatasetItem:
    if isinstance(raw, DatasetItem):
        return raw
    if not isinstance(raw, dict):
        raise TypeError(f"dataset items must be dicts, got {type(raw).__name__}")

    if "input" in raw:
        return DatasetItem(
            id=raw.get("id") or new_id(),
            input=raw["input"] if isinstance(raw["input"], dict) else {"input": raw["input"]},
            expected_output=raw.get("expected_output"),
            metadata=raw.get("metadata") or {},
            dataset_id=dataset_id,
        )
    return DatasetItem(id=new_id(), input=raw, dataset_id=dataset_id)
