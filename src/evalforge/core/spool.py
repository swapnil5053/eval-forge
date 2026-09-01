"""NDJSON spool writer.

Traced processes never open the DuckDB file. They append JSON lines to their own
spool file under ``~/.evalforge/spool``, and the server process ingests those
files into DuckDB. One file per process removes write contention entirely, and
traces survive being recorded while no server is running.

A file being appended to is named ``*.ndjson.active``; the ingester only reads
``*.ndjson``, so it never sees a half-written line. Files rotate on size or age.
"""

import atexit
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger(__name__)

ACTIVE_SUFFIX = ".ndjson.active"
SEALED_SUFFIX = ".ndjson"

FLUSH_LINES = 100
FLUSH_SECONDS = 5.0
ROTATE_LINES = 1000
ROTATE_SECONDS = 10.0


def default_home() -> Path:
    return Path(os.environ.get("EVALFORGE_HOME", Path.home() / ".evalforge"))


def default_spool_dir() -> Path:
    return default_home() / "spool"


class SpoolWriter:
    """Appends records as NDJSON lines to a per-process spool file."""

    def __init__(
        self,
        spool_dir: Optional[Path] = None,
        flush_lines: int = FLUSH_LINES,
        flush_seconds: float = FLUSH_SECONDS,
        rotate_lines: int = ROTATE_LINES,
        rotate_seconds: float = ROTATE_SECONDS,
    ) -> None:
        self.spool_dir = Path(spool_dir) if spool_dir else default_spool_dir()
        self.spool_dir.mkdir(parents=True, exist_ok=True)

        self._flush_lines = flush_lines
        self._flush_seconds = flush_seconds
        self._rotate_lines = rotate_lines
        self._rotate_seconds = rotate_seconds

        self._lock = threading.Lock()
        self._buffer: list[str] = []
        self._closed = False
        self._handle = None
        self._path: Optional[Path] = None
        self._opened_at = 0.0
        self._lines_in_file = 0
        self._sequence = 0

        self._open_file()

        self._wakeup = threading.Event()
        self._flusher = threading.Thread(
            target=self._flush_loop, name="evalforge-spool-flush", daemon=True
        )
        self._flusher.start()
        atexit.register(self.close)

    @property
    def path(self) -> Optional[Path]:
        return self._path

    @property
    def closed(self) -> bool:
        return self._closed

    def write(self, record: dict) -> None:
        line = json.dumps(record, separators=(",", ":"))
        with self._lock:
            if self._closed:
                LOGGER.debug("dropping spool record written after close: %s", record.get("type"))
                return
            self._buffer.append(line)
            if len(self._buffer) >= self._flush_lines:
                self._flush_locked()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._flush_locked()
            self._seal_locked()
        self._wakeup.set()

    def _open_file(self) -> None:
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        name = f"{stamp}_{os.getpid()}_{self._sequence:04d}"
        self._sequence += 1
        self._path = self.spool_dir / f"{name}{ACTIVE_SUFFIX}"
        self._handle = self._path.open("a", encoding="utf-8")
        self._opened_at = time.monotonic()
        self._lines_in_file = 0

    def _flush_locked(self) -> None:
        if self._buffer and self._handle is not None:
            self._handle.write("".join(f"{line}\n" for line in self._buffer))
            self._handle.flush()
            self._lines_in_file += len(self._buffer)
            self._buffer.clear()

        if self._closed or self._handle is None:
            return

        aged = time.monotonic() - self._opened_at >= self._rotate_seconds
        if self._lines_in_file and (aged or self._lines_in_file >= self._rotate_lines):
            self._seal_locked()
            self._open_file()

    def _seal_locked(self) -> None:
        if self._handle is None or self._path is None:
            return
        self._handle.close()
        self._handle = None
        path, self._path = self._path, None
        if self._lines_in_file == 0:
            path.unlink(missing_ok=True)
            return
        path.rename(path.with_name(path.name[: -len(ACTIVE_SUFFIX)] + SEALED_SUFFIX))

    def _flush_loop(self) -> None:
        while not self._wakeup.wait(self._flush_seconds):
            self.flush()


_writer: Optional[SpoolWriter] = None
_writer_lock = threading.Lock()


def get_writer() -> SpoolWriter:
    """Return the process-wide spool writer, creating it on first use."""
    global _writer
    with _writer_lock:
        if _writer is None or _writer.closed:
            _writer = SpoolWriter()
        return _writer


def set_writer(writer: Optional[SpoolWriter]) -> None:
    """Replace the process-wide writer. Tests use this to spool into tmp_path."""
    global _writer
    with _writer_lock:
        _writer = writer
