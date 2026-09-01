"""DuckDB storage, owned by the server process.

DuckDB allows a single writer, so exactly one process opens the database for
writing: whichever one runs ingestion (``evalforge ingest`` or the dashboard).
Everything else opens it read-only. Traced applications never touch it at all -
they append to the spool (see :mod:`evalforge.core.spool`).
"""

import datetime
import json
import logging
from pathlib import Path
from typing import Any, Iterable, Optional

import duckdb

from ..core.spool import default_home

LOGGER = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schemas.sql")

_TRACE_COLUMNS = ("id", "name", "start_time", "end_time", "status", "tags", "metadata")
_SPAN_COLUMNS = (
    "id",
    "trace_id",
    "parent_span_id",
    "name",
    "type",
    "start_time",
    "end_time",
    "status",
    "input",
    "output",
    "error",
    "model",
    "prompt_tokens",
    "completion_tokens",
    "estimated_cost_usd",
    "tags",
    "metadata",
)
_SCORE_COLUMNS = ("id", "span_id", "name", "value", "reason", "source", "created_at")
_JSON_COLUMNS = frozenset({"tags", "metadata", "input", "output"})
# Spool records are partial by design: a span is written once when it starts and
# again when it ends. These fill the columns the first write cannot know.
_DEFAULTS = {"status": "ok", "type": "general", "source": "sdk"}
_TIME_COLUMNS = frozenset({"start_time", "end_time", "created_at"})


def default_db_path() -> Path:
    return default_home() / "evalforge.db"


class Store:
    """A DuckDB connection plus the upserts ingestion needs."""

    def __init__(self, path: Optional[Path] = None, read_only: bool = False) -> None:
        self.path = Path(path) if path else default_db_path()
        self.read_only = read_only
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = duckdb.connect(str(self.path), read_only=read_only)
        if not read_only:
            self.db.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def upsert_traces(self, records: Iterable[dict]) -> int:
        return self._upsert("traces", _TRACE_COLUMNS, records)

    def upsert_spans(self, records: Iterable[dict]) -> int:
        return self._upsert("spans", _SPAN_COLUMNS, records)

    def upsert_feedback_scores(self, records: Iterable[dict]) -> int:
        return self._upsert("feedback_scores", _SCORE_COLUMNS, records)

    def count(self, table: str) -> int:
        if table not in ("traces", "spans", "feedback_scores"):
            raise ValueError(f"unknown table: {table}")
        return self.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def _upsert(self, table: str, columns: tuple, records: Iterable[dict]) -> int:
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


def _encode(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column in _JSON_COLUMNS:
        return json.dumps(value) if not isinstance(value, str) else value
    if column in _TIME_COLUMNS and isinstance(value, str):
        return datetime.datetime.fromisoformat(value)
    return value
