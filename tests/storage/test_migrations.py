import duckdb
import pytest

from evalforge.storage import migrations
from evalforge.storage.duckdb_store import Store

EXPECTED_TABLES = {
    "traces",
    "spans",
    "feedback_scores",
    "datasets",
    "dataset_items",
    "experiments",
    "experiment_results",
    "schema_version",
}


def table_names(db):
    return {row[0] for row in db.execute("SELECT table_name FROM duckdb_tables()").fetchall()}


def test_every_migration_is_numbered():
    versions = [migration.version for migration in migrations.available()]
    assert versions == sorted(versions)
    assert versions[0] == 1


def test_store_creates_every_table(tmp_path):
    with Store(tmp_path / "evalforge.db") as store:
        assert EXPECTED_TABLES <= table_names(store.db)
        assert migrations.current_version(store.db) == len(migrations.available())


def test_migrations_are_applied_once(tmp_path):
    path = tmp_path / "evalforge.db"
    with Store(path):
        pass

    db = duckdb.connect(str(path))
    assert migrations.apply(db) == []
    assert db.execute("SELECT count(*) FROM schema_version").fetchone()[0] == len(
        migrations.available()
    )
    db.close()


def test_a_new_migration_is_picked_up(tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "001_first.sql").write_text("CREATE TABLE alpha (id VARCHAR)")

    db = duckdb.connect()
    assert [migration.name for migration in migrations.apply(db, directory)] == ["first"]

    (directory / "002_second.sql").write_text("CREATE TABLE beta (id VARCHAR)")
    assert [migration.name for migration in migrations.apply(db, directory)] == ["second"]
    assert {"alpha", "beta"} <= table_names(db)
    assert migrations.current_version(db) == 2
    db.close()


def test_a_failing_migration_rolls_back(tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "001_broken.sql").write_text(
        "CREATE TABLE alpha (id VARCHAR); SELECT nonexistent_function();"
    )

    db = duckdb.connect()
    with pytest.raises(duckdb.Error):
        migrations.apply(db, directory)

    assert "alpha" not in table_names(db)
    assert migrations.current_version(db) == 0
    db.close()


def test_badly_named_migration_is_rejected(tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "add_stuff.sql").write_text("SELECT 1")

    with pytest.raises(ValueError, match="001_name.sql"):
        migrations.available(directory)
