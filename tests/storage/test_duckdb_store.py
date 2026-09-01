import datetime
import json

import pytest

from evalforge.storage.duckdb_store import Store


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "evalforge.db") as opened:
        yield opened


def span_record(span_id="s1", **overrides):
    record = {
        "id": span_id,
        "trace_id": "t1",
        "name": "answer",
        "type": "general",
        "start_time": "2026-09-01T10:00:00+00:00",
        "status": "ok",
        "input": {"query": "hi"},
        "tags": {},
        "metadata": {},
    }
    record.update(overrides)
    return record


def test_schema_is_created(store):
    assert store.count("traces") == 0
    assert store.count("spans") == 0
    assert store.count("feedback_scores") == 0


def test_insert_and_read_back(store):
    store.upsert("spans", [span_record()])

    row = store.db.execute(
        "SELECT name, status, start_time, input FROM spans WHERE id = 's1'"
    ).fetchone()
    assert row[0] == "answer"
    assert row[1] == "ok"
    assert row[2].tzinfo is not None
    assert row[3] == '{"query": "hi"}'


def test_start_then_end_merges_into_one_row(store):
    store.upsert("spans", [span_record()])
    store.upsert("spans", 
        [
            span_record(
                end_time="2026-09-01T10:00:02+00:00",
                status="error",
                error="boom",
                output=None,
            )
        ]
    )

    assert store.count("spans") == 1
    row = store.db.execute(
        "SELECT status, error, end_time, input FROM spans WHERE id = 's1'"
    ).fetchone()
    assert row[0] == "error"
    assert row[1] == "boom"
    assert row[2] == datetime.datetime(
        2026, 9, 1, 10, 0, 2, tzinfo=datetime.timezone.utc
    )
    assert row[3] == '{"query": "hi"}'


def test_a_later_null_does_not_erase_a_value(store):
    store.upsert("spans", [span_record(model="gpt-4o", prompt_tokens=10)])
    store.upsert("spans", [span_record()])

    row = store.db.execute(
        "SELECT model, prompt_tokens FROM spans WHERE id = 's1'"
    ).fetchone()
    assert row == ("gpt-4o", 10)


def test_read_only_connection_cannot_write(tmp_path):
    path = tmp_path / "evalforge.db"
    with Store(path) as store:
        store.upsert("spans", [span_record()])

    with Store(path, read_only=True) as reader:
        assert reader.count("spans") == 1
        with pytest.raises(Exception):
            reader.upsert("spans", [span_record("s2")])


def test_unknown_table_is_rejected(store):
    with pytest.raises(ValueError, match="unknown table"):
        store.count("spans; DROP TABLE spans")


def test_string_output_is_stored_as_valid_json(store):
    store.upsert("spans", [span_record(output="Paris is the capital.")])

    stored, = store.db.execute("SELECT output FROM spans WHERE id = 's1'").fetchone()
    assert json.loads(stored) == "Paris is the capital."
