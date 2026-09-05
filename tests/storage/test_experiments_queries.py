import datetime
import json

import pytest

from evalforge.storage import queries
from evalforge.storage.duckdb_store import Store

BASE = datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.timezone.utc)


def score(value, higher_is_better=True, reason="because"):
    return {"value": value, "higher_is_better": higher_is_better, "reason": reason}


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "evalforge.db") as opened:
        _seed(opened)
        yield opened


def _seed(store):
    store.upsert("datasets", [{"id": "d1", "name": "capitals", "description": "toy",
                               "created_at": BASE}])
    store.upsert(
        "dataset_items",
        [
            {"id": "i1", "dataset_id": "d1", "input": {"question": "France?"},
             "expected_output": "Paris", "created_at": BASE},
            {"id": "i2", "dataset_id": "d1", "input": {"question": "Japan?"},
             "expected_output": "Tokyo", "created_at": BASE},
        ],
    )
    store.upsert("experiments", [
        {"id": "e1", "name": "v1", "dataset_id": "d1", "created_at": BASE},
        {"id": "e2", "name": "v2", "dataset_id": "d1",
         "created_at": BASE + datetime.timedelta(minutes=5)},
    ])
    store.upsert("experiment_results", [
        {"id": "r1", "experiment_id": "e1", "dataset_item_id": "i1", "trace_id": "t1",
         "output": "Paris.", "latency_ms": 120.0, "created_at": BASE,
         "scores": {"faithfulness": score(0.8), "hallucination": score(0.2, False)}},
        {"id": "r2", "experiment_id": "e1", "dataset_item_id": "i2",
         "output": "Kyoto.", "latency_ms": 140.0, "created_at": BASE,
         "scores": {"faithfulness": score(0.4), "hallucination": score(0.6, False)}},
        {"id": "r3", "experiment_id": "e2", "dataset_item_id": "i1",
         "output": "Paris.", "latency_ms": 90.0, "created_at": BASE,
         "scores": {"faithfulness": score(0.9), "hallucination": score(0.1, False)}},
        {"id": "r4", "experiment_id": "e2", "dataset_item_id": "i2",
         "output": None, "latency_ms": 30.0, "created_at": BASE,
         "error": "RuntimeError: boom", "scores": {}},
    ])


def test_experiments_are_summarised_newest_first(store):
    rows = queries.experiments(store)

    assert [row.name for row in rows] == ["v2", "v1"]
    v1 = rows[1]
    assert v1.items == 2
    assert v1.errors == 0
    assert v1.means["faithfulness"] == pytest.approx(0.6)
    assert v1.polarity == {"faithfulness": True, "hallucination": False}
    assert v1.metrics == ["faithfulness", "hallucination"]


def test_an_errored_item_counts_but_does_not_score(store):
    v2 = queries.experiment(store, "v2")
    assert v2.items == 2
    assert v2.errors == 1
    assert v2.means["faithfulness"] == pytest.approx(0.9)


def test_experiment_items_carry_the_dataset_input(store):
    items = queries.experiment_items(store, "v1")

    assert [item.dataset_item_id for item in items] == ["i1", "i2"]
    assert items[0].input == {"question": "France?"}
    assert items[0].trace_id == "t1"
    assert items[0].scores["faithfulness"]["value"] == 0.8


def test_missing_experiment(store):
    assert queries.experiment(store, "absent") is None
    assert queries.experiment_items(store, "absent") == []


def test_compare_experiments_pairs_by_item(store):
    rows = queries.compare_experiments(store, "v1", "v2")

    assert [row["dataset_item_id"] for row in rows] == ["i1", "i2"]
    faithful = rows[0]["metrics"]["faithfulness"]
    assert (faithful["left"], faithful["right"]) == (0.8, 0.9)
    assert faithful["higher_is_better"] is True
    assert rows[0]["metrics"]["hallucination"]["higher_is_better"] is False


def test_compare_handles_a_side_with_no_scores(store):
    rows = queries.compare_experiments(store, "v1", "v2")
    second = rows[1]["metrics"]["faithfulness"]
    assert second["left"] == 0.4
    assert second["right"] is None


def test_datasets_and_items(store):
    datasets = queries.datasets(store)
    assert [(row.name, row.items) for row in datasets] == [("capitals", 2)]
    assert datasets[0].created_at.tzinfo is not None

    items = queries.dataset_items(store, "capitals")
    assert [item["expected_output"] for item in items] == ["Paris", "Tokyo"]
    assert items[0]["input"] == {"question": "France?"}


def test_dataset_items_of_an_unknown_dataset(store):
    assert queries.dataset_items(store, "absent") == []


def test_scores_survive_the_json_round_trip(store):
    stored, = store.db.execute(
        "SELECT scores FROM experiment_results WHERE id = 'r1'"
    ).fetchone()
    assert json.loads(stored)["hallucination"]["higher_is_better"] is False
