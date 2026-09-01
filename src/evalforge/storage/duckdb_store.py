"""DuckDB storage, owned by whichever process holds the write lock.

DuckDB allows a single writer, so exactly one process opens the database for
writing: whichever one runs ingestion (``evalforge ingest``, the dashboard) or an
evaluation. Everything else opens it read-only. Traced applications never touch it
at all - they append to the spool (see :mod:`evalforge.core.spool`).
"""

import datetime
import json
import logging
from pathlib import Path
from typing import Any, Iterable, Optional

import duckdb

from ..core.spool import default_home
from . import migrations

LOGGER = logging.getLogger(__name__)

TABLES = {
    "traces": ("id", "name", "start_time", "end_time", "status", "tags", "metadata"),
    "spans": (
        "id", "trace_id", "parent_span_id", "name", "type", "start_time", "end_time",
        "status", "input", "output", "error", "model", "prompt_tokens",
        "completion_tokens", "estimated_cost_usd", "tags", "metadata",
    ),
    "feedback_scores": (
        "id", "span_id", "name", "value", "reason", "source", "created_at",
    ),
    "datasets": ("id", "name", "description", "created_at", "metadata"),
    "dataset_items": (
        "id", "dataset_id", "input", "expected_output", "metadata", "created_at",
    ),
    "experiments": ("id", "name", "dataset_id", "created_at", "metadata"),
    "experiment_results": (
        "id", "experiment_id", "dataset_item_id", "trace_id", "output", "scores",
        "latency_ms", "error", "created_at",
    ),
    "faithfulness_audits": (
        "id", "trace_id", "span_id", "query", "answer", "context", "score",
        "claim_count", "unsupported", "contradicted", "model", "created_at",
    ),
    "audit_claims": (
        "id", "audit_id", "position", "claim", "verdict", "severity", "evidence",
        "rationale",
    ),
    "token_attributions": (
        "id", "span_id", "trace_id", "method", "text", "tokens", "scores", "baseline",
        "created_at",
    ),
}

# Spool records are partial by design: a span is written once when it starts and
# again when it ends. These fill the columns the first write cannot know.
_DEFAULTS = {"status": "ok", "type": "general", "source": "sdk"}
_JSON_COLUMNS = frozenset(
    {
        "tags", "metadata", "input", "output", "expected_output", "scores", "context",
        "evidence", "tokens",
    }
)
_TIME_COLUMNS = frozenset({"start_time", "end_time", "created_at"})


class DatabaseLocked(RuntimeError):
    """Another process holds the DuckDB write lock."""


def default_db_path() -> Path:
    return default_home() / "evalforge.db"


class Store:
    """A DuckDB connection plus the upserts ingestion and evaluation need."""

    def __init__(self, path: Optional[Path] = None, read_only: bool = False) -> None:
        self.path = Path(path) if path else default_db_path()
        self.read_only = read_only
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.db = duckdb.connect(str(self.path), read_only=read_only)
        except duckdb.IOException as error:
            raise DatabaseLocked(
                f"{self.path} is locked by another process. Stop 'evalforge ingest "
                f"--watch' or the dashboard, then try again."
            ) from error
        if not read_only:
            migrations.apply(self.db)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def upsert(self, table: str, records: Iterable[dict]) -> int:
        """Insert records, merging into any row that already has the same id."""
        columns = self._columns(table)
        rows = [
            tuple(
                _encode(column, record.get(column, _DEFAULTS.get(column)))
                for column in columns
            )
            for record in records
        ]
        if not rows:
            return 0

        placeholders = ", ".join("?" for _ in columns)
        # A span arrives twice, as span_start then span_end. COALESCE keeps whichever
        # write carried a value, so the two halves merge in either order.
        updates = ", ".join(
            f"{column} = COALESCE(excluded.{column}, {table}.{column})"
            for column in columns
            if column != "id"
        )
        self.db.executemany(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT (id) DO UPDATE SET {updates}",
            rows,
        )
        return len(rows)

    def count(self, table: str) -> int:
        return self.db.execute(f"SELECT count(*) FROM {self._name(table)}").fetchone()[0]

    def _columns(self, table: str) -> tuple:
        return TABLES[self._name(table)]

    def _name(self, table: str) -> str:
        if table not in TABLES:
            raise ValueError(f"unknown table: {table}")
        return table


def _encode(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column in _JSON_COLUMNS:
        # Spool values arrive already decoded, so a str here is a plain string
        # output and still needs quoting to be valid JSON.
        return json.dumps(value, default=str)
    if column in _TIME_COLUMNS and isinstance(value, str):
        return datetime.datetime.fromisoformat(value)
    return value
