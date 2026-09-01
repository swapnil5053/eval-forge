"""Spool to DuckDB ingestion.

Sealed spool files (``*.ndjson``) are read whole, batched into DuckDB, and then
deleted. Files still being appended to end in ``.ndjson.active`` and are left
alone until their writer seals them - unless they have gone untouched for
``STALE_SECONDS``, which means the process that owned them died, in which case
they are adopted and sealed here.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..core.spool import ACTIVE_SUFFIX, SEALED_SUFFIX, default_spool_dir
from .duckdb_store import Store

LOGGER = logging.getLogger(__name__)

STALE_SECONDS = 300.0
POLL_SECONDS = 2.0

_RECORD_TABLES = {
    "trace_start": "traces",
    "trace_end": "traces",
    "span_start": "spans",
    "span_end": "spans",
    "feedback_score": "feedback_scores",
}


@dataclass
class IngestResult:
    files: int = 0
    traces: int = 0
    spans: int = 0
    feedback_scores: int = 0
    skipped_lines: int = 0

    @property
    def records(self) -> int:
        return self.traces + self.spans + self.feedback_scores


def ingest_once(store: Store, spool_dir: Optional[Path] = None) -> IngestResult:
    """Ingest every sealed spool file, deleting each one after it lands."""
    spool_dir = Path(spool_dir) if spool_dir else default_spool_dir()
    result = IngestResult()
    if not spool_dir.is_dir():
        return result

    _adopt_abandoned(spool_dir)

    for path in sorted(spool_dir.glob(f"*{SEALED_SUFFIX}")):
        batches, skipped = _read(path)
        result.skipped_lines += skipped
        result.traces += store.upsert("traces", batches["traces"])
        result.spans += store.upsert("spans", batches["spans"])
        result.feedback_scores += store.upsert("feedback_scores", batches["feedback_scores"])
        path.unlink(missing_ok=True)
        result.files += 1

    return result


def _read(path: Path) -> tuple:
    batches: dict = {"traces": [], "spans": [], "feedback_scores": []}
    skipped = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                LOGGER.debug("skipping malformed line in %s: %s", path.name, error)
                skipped += 1
                continue
            table = _RECORD_TABLES.get(record.get("type"))
            if table is None:
                LOGGER.debug("skipping record of unknown type %r", record.get("type"))
                skipped += 1
                continue
            if table == "spans" and "span_type" in record:
                record["type"] = record.pop("span_type")
            batches[table].append(record)
    return batches, skipped


def _adopt_abandoned(spool_dir: Path) -> None:
    cutoff = time.time() - STALE_SECONDS
    for path in spool_dir.glob(f"*{ACTIVE_SUFFIX}"):
        if path.stat().st_mtime > cutoff:
            continue
        sealed = path.with_name(path.name[: -len(ACTIVE_SUFFIX)] + SEALED_SUFFIX)
        try:
            path.rename(sealed)
        except OSError as error:
            LOGGER.debug("could not adopt stale spool file %s: %s", path.name, error)
        else:
            LOGGER.info("adopted abandoned spool file %s", path.name)


class Ingestor:
    """Runs :func:`ingest_once` on a background thread until stopped."""

    def __init__(
        self,
        store: Store,
        spool_dir: Optional[Path] = None,
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        self.store = store
        self.spool_dir = Path(spool_dir) if spool_dir else default_spool_dir()
        self.poll_seconds = poll_seconds
        self.total = IngestResult()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="evalforge-ingest", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._thread.join(timeout)

    def _run(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                result = ingest_once(self.store, self.spool_dir)
            except Exception as error:
                LOGGER.error("ingestion pass failed: %s", error, exc_info=error)
                continue
            self.total.files += result.files
            self.total.traces += result.traces
            self.total.spans += result.spans
            self.total.feedback_scores += result.feedback_scores
