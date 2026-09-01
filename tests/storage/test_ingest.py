import json
import time

from evalforge import trace
from evalforge.core import spool
from evalforge.storage.duckdb_store import Store
from evalforge.storage.ingest import ingest_once


def write_spool_file(directory, records, sealed=True):
    directory.mkdir(parents=True, exist_ok=True)
    suffix = spool.SEALED_SUFFIX if sealed else spool.ACTIVE_SUFFIX
    path = directory / f"20260901T100000_1234{suffix}"
    path.write_text(
        "".join(f"{json.dumps(record)}\n" for record in records), encoding="utf-8"
    )
    return path


def test_ingests_and_deletes_sealed_files(tmp_path):
    directory = tmp_path / "spool"
    path = write_spool_file(
        directory,
        [
            {
                "type": "trace_start",
                "id": "t1",
                "name": "answer",
                "start_time": "2026-09-01T10:00:00+00:00",
            },
            {
                "type": "span_start",
                "id": "s1",
                "trace_id": "t1",
                "name": "answer",
                "start_time": "2026-09-01T10:00:00+00:00",
            },
            {
                "type": "span_end",
                "id": "s1",
                "trace_id": "t1",
                "name": "answer",
                "start_time": "2026-09-01T10:00:00+00:00",
                "end_time": "2026-09-01T10:00:01+00:00",
                "status": "ok",
            },
        ],
    )

    with Store(tmp_path / "evalforge.db") as store:
        result = ingest_once(store, directory)

        assert result.files == 1
        assert store.count("traces") == 1
        assert store.count("spans") == 1

    assert not path.exists()


def test_active_files_are_left_alone(tmp_path):
    directory = tmp_path / "spool"
    path = write_spool_file(directory, [{"type": "trace_start", "id": "t1"}], sealed=False)

    with Store(tmp_path / "evalforge.db") as store:
        result = ingest_once(store, directory)

    assert result.files == 0
    assert path.exists()


def test_abandoned_active_files_are_adopted(tmp_path, monkeypatch):
    directory = tmp_path / "spool"
    write_spool_file(
        directory,
        [
            {
                "type": "trace_start",
                "id": "t1",
                "name": "answer",
                "start_time": "2026-09-01T10:00:00+00:00",
            }
        ],
        sealed=False,
    )
    monkeypatch.setattr("evalforge.storage.ingest.STALE_SECONDS", -1.0)

    with Store(tmp_path / "evalforge.db") as store:
        result = ingest_once(store, directory)
        assert result.files == 1
        assert store.count("traces") == 1


def test_malformed_lines_are_skipped_not_fatal(tmp_path):
    directory = tmp_path / "spool"
    directory.mkdir()
    (directory / f"20260901T100000_1{spool.SEALED_SUFFIX}").write_text(
        '{"type": "trace_start", "id": "t1", "name": "a", '
        '"start_time": "2026-09-01T10:00:00+00:00"}\n'
        "not json\n"
        '{"type": "wat", "id": "x"}\n',
        encoding="utf-8",
    )

    with Store(tmp_path / "evalforge.db") as store:
        result = ingest_once(store, directory)

    assert result.traces == 1
    assert result.skipped_lines == 2


def test_missing_spool_directory_is_not_an_error(tmp_path):
    with Store(tmp_path / "evalforge.db") as store:
        assert ingest_once(store, tmp_path / "absent").files == 0


def test_end_to_end_trace_to_duckdb(tmp_path):
    directory = tmp_path / "spool"
    writer = spool.SpoolWriter(directory)
    spool.set_writer(writer)
    try:

        @trace
        def child(query):
            return {"model": "gpt-4o", "usage": {"prompt_tokens": 5, "completion_tokens": 2}}

        @trace(name="pipeline")
        def parent(query):
            return child(query)

        parent("who?")
    finally:
        writer.close()
        spool.set_writer(None)

    with Store(tmp_path / "evalforge.db") as store:
        ingest_once(store, directory)

        assert store.count("traces") == 1
        assert store.count("spans") == 2
        row = store.db.execute(
            "SELECT type, model, prompt_tokens, completion_tokens FROM spans "
            "WHERE name = 'child'"
        ).fetchone()
        assert row == ("llm", "gpt-4o", 5, 2)

        parent_id, = store.db.execute(
            "SELECT id FROM spans WHERE name = 'pipeline'"
        ).fetchone()
        child_parent, = store.db.execute(
            "SELECT parent_span_id FROM spans WHERE name = 'child'"
        ).fetchone()
        assert child_parent == parent_id

        latency = store.db.execute(
            "SELECT epoch_ms(end_time) - epoch_ms(start_time) FROM traces"
        ).fetchone()[0]
        assert latency >= 0
