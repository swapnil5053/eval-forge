"""Schema migrations.

Every ``NNN_name.sql`` file in ``migrations/`` runs once, in numeric order, and
its number is recorded in ``schema_version``. A database created by an older
release catches up on the next write connection; nothing re-runs.
"""

import logging
import re
from pathlib import Path
from typing import List, NamedTuple

import duckdb

LOGGER = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
FILENAME = re.compile(r"^(\d+)_(.+)\.sql$")

_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    name       VARCHAR NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


class Migration(NamedTuple):
    version: int
    name: str
    path: Path


def available(directory: Path = MIGRATIONS_DIR) -> List[Migration]:
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        match = FILENAME.match(path.name)
        if match is None:
            raise ValueError(
                f"migration filename must look like 001_name.sql, got {path.name}"
            )
        migrations.append(Migration(int(match.group(1)), match.group(2), path))

    versions = [migration.version for migration in migrations]
    if len(set(versions)) != len(versions):
        raise ValueError(f"duplicate migration versions in {directory}")
    return migrations


def current_version(db: duckdb.DuckDBPyConnection) -> int:
    tables = db.execute(
        "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'schema_version'"
    ).fetchone()[0]
    if not tables:
        return 0
    return db.execute("SELECT coalesce(max(version), 0) FROM schema_version").fetchone()[0]


def apply(db: duckdb.DuckDBPyConnection, directory: Path = MIGRATIONS_DIR) -> List[Migration]:
    """Run every migration newer than the recorded version. Returns what ran."""
    db.execute(_VERSION_TABLE)
    version = current_version(db)

    applied = []
    for migration in available(directory):
        if migration.version <= version:
            continue
        LOGGER.debug("applying migration %03d_%s", migration.version, migration.name)
        db.execute("BEGIN TRANSACTION")
        try:
            db.execute(migration.path.read_text(encoding="utf-8"))
            db.execute(
                "INSERT INTO schema_version (version, name) VALUES (?, ?)",
                [migration.version, migration.name],
            )
        except Exception:
            db.execute("ROLLBACK")
            raise
        db.execute("COMMIT")
        applied.append(migration)

    if applied:
        LOGGER.info("applied %d migration(s)", len(applied))
    return applied
