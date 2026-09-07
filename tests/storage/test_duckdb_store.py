import datetime
import json

import duckdb
import pytest

from evalforge.storage import duckdb_store as store_module
from evalforge.storage.duckdb_store import Store

_WHEN = datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.timezone.utc)


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

    # epoch_ms rather than the column itself: reading a TIMESTAMPTZ makes DuckDB
    # import pytz, which is not a dependency of this package, so a test that does
    # it only passes on a machine that happens to have pytz for other reasons.
    row = store.db.execute(
        "SELECT name, status, epoch_ms(start_time), input FROM spans WHERE id = 's1'"
    ).fetchone()
    assert row[0] == "answer"
    assert row[1] == "ok"
    assert row[2] == int(
        datetime.datetime(
            2026, 9, 1, 10, 0, tzinfo=datetime.timezone.utc
        ).timestamp() * 1000
    )
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
        "SELECT status, error, epoch_ms(end_time), input FROM spans WHERE id = 's1'"
    ).fetchone()
    assert row[0] == "error"
    assert row[1] == "boom"
    assert row[2] == int(
        datetime.datetime(
            2026, 9, 1, 10, 0, 2, tzinfo=datetime.timezone.utc
        ).timestamp() * 1000
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


def test_two_halves_of_a_span_merge_even_inside_one_batch(tmp_path):
    """Batched inserts apply the conflict clause once per statement.

    Both halves in one call must still merge, or every span ingested from a single
    spool file would keep its start and lose its end.
    """
    with Store(tmp_path / "merge.db") as store:
        store.upsert(
            "spans",
            [
                {"id": "s1", "trace_id": "t1", "name": "generate", "start_time": _WHEN},
                {"id": "s1", "end_time": _WHEN, "output": "done", "prompt_tokens": 12},
            ],
        )
        row = store.db.execute(
            "SELECT name, output, prompt_tokens, end_time IS NOT NULL FROM spans"
        ).fetchone()

    assert row == ("generate", '"done"', 12, True)


def test_a_repeated_id_far_apart_still_merges(tmp_path):
    """The split has to survive a batch boundary, not just the row next door."""
    filler = [
        {"id": f"f{index}", "trace_id": "t1", "name": "x", "start_time": _WHEN}
        for index in range(store_module.BATCH_ROWS + 25)
    ]
    with Store(tmp_path / "far.db") as store:
        store.upsert(
            "spans",
            [{"id": "s1", "trace_id": "t1", "name": "generate", "start_time": _WHEN}]
            + filler
            + [{"id": "s1", "output": "done"}],
        )
        assert store.count("spans") == len(filler) + 1
        assert store.db.execute(
            "SELECT name, output FROM spans WHERE id = 's1'"
        ).fetchone() == ("generate", '"done"')


def test_a_failed_batch_leaves_nothing_behind(tmp_path):
    with Store(tmp_path / "rollback.db") as store:
        with pytest.raises(duckdb.Error):
            store.upsert("spans", [{"id": "ok", "name": "a"}, {"trace_id": "no id"}])
        assert store.count("spans") == 0


def test_text_is_stored_as_written_not_as_escapes(tmp_path):
    """ensure_ascii would put \\u00e9 in the column and the panel would show it."""
    with Store(tmp_path / "unicode.db") as store:
        store.upsert(
            "spans",
            [
                {
                    "id": "s1",
                    "trace_id": "t1",
                    "name": "generate",
                    "start_time": _WHEN,
                    "output": {"answer": "un café — 東京"},
                }
            ],
        )
        stored = store.db.execute("SELECT output FROM spans").fetchone()[0]

    assert "café" in stored
    assert "東京" in stored
    assert "\\u" not in stored
