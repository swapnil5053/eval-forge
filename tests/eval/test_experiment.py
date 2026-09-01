import pytest

from evalforge import trace
from evalforge.core import spool
from evalforge.eval import dataset, metrics
from evalforge.eval.experiment import evaluate
from evalforge.storage.duckdb_store import Store

ITEMS = [
    {"input": {"question": "capital of France?", "context": ["Paris is the capital."]},
     "expected_output": "Paris"},
    {"input": {"question": "capital of Japan?", "context": ["Tokyo is the capital."]},
     "expected_output": "Tokyo"},
]


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "evalforge.db") as opened:
        yield opened


@pytest.fixture
def spooled(tmp_path):
    writer = spool.SpoolWriter(tmp_path / "spool")
    spool.set_writer(writer)
    yield writer
    writer.close()
    spool.set_writer(None)


def answer(item):
    return f"The answer is {item['question'].split()[-1].rstrip('?')}."


def test_runs_every_item_and_scores_it(store, judge_stub):
    result = evaluate(
        dataset=ITEMS,
        task=answer,
        metrics=[metrics.faithfulness, metrics.answer_relevance],
        name="baseline",
        store=store,
    )

    assert len(result.results) == 2
    assert result.errors == 0
    assert set(result.means()) == {"faithfulness", "answer_relevance"}
    assert result.means()["faithfulness"] == pytest.approx(0.75)
    assert all(item.latency_ms is not None for item in result.results)


def test_metrics_receive_the_question_and_context(store, judge_stub):
    evaluate(dataset=ITEMS[:1], task=answer, metrics=[metrics.faithfulness], store=store)

    user = judge_stub.calls[0]["user"]
    assert "capital of France?" in user
    assert "Paris is the capital." in user


def test_metrics_only_receive_arguments_they_declare(store, judge_stub):
    calls = []

    def picky(output, model="ignored"):
        calls.append(output)
        return metrics.Score(metric_name="picky", value=1.0)

    evaluate(dataset=ITEMS, task=answer, metrics=[picky], store=store)
    assert calls == ["The answer is France.", "The answer is Japan."]


def test_a_failing_task_is_recorded_not_raised(store, judge_stub):
    def broken(item):
        raise RuntimeError("vector store unreachable")

    result = evaluate(dataset=ITEMS, task=broken, metrics=[metrics.faithfulness], store=store)

    assert result.errors == 2
    assert result.results[0].error == "RuntimeError: vector store unreachable"
    assert result.results[0].scores == {}
    assert all(item.failed for item in result.results)


def test_a_failing_metric_is_recorded_per_item(store, judge_stub):
    def exploding(output):
        raise ValueError("judge unavailable")

    result = evaluate(dataset=ITEMS, task=answer, metrics=[exploding], store=store)

    assert result.results[0].errors == {"exploding": "ValueError: judge unavailable"}
    assert result.means() == {}


def test_results_are_persisted(store, judge_stub):
    result = evaluate(
        dataset=ITEMS, task=answer, metrics=[metrics.faithfulness], name="run-1", store=store
    )

    assert store.count("experiments") == 1
    assert store.count("experiment_results") == 2
    stored = store.db.execute(
        "SELECT scores FROM experiment_results ORDER BY dataset_item_id"
    ).fetchall()
    assert '"faithfulness"' in stored[0][0]
    assert result.name == "run-1"


def test_a_named_dataset_is_used(store, judge_stub):
    dataset.create(store, "capitals", ITEMS)

    result = evaluate(dataset="capitals", task=answer, metrics=[], store=store)

    assert result.dataset_name == "capitals"
    assert len(result.results) == 2


def test_an_empty_dataset_is_rejected(store, judge_stub):
    with pytest.raises(ValueError, match="nothing to evaluate"):
        evaluate(dataset=[], task=answer, store=store)


def test_traces_from_the_task_are_ingested_and_linked(store, judge_stub, spooled):
    @trace(name="answer")
    def traced(item):
        return answer(item)

    result = evaluate(dataset=ITEMS, task=traced, metrics=[], store=store)

    assert store.count("traces") == 2
    assert all(item.trace_id for item in result.results)
    stored = {row[0] for row in store.db.execute("SELECT id FROM traces").fetchall()}
    assert {item.trace_id for item in result.results} == stored


def test_polarity_is_reported_per_metric(store, judge_stub):
    judge_stub.default = {"score": 0.2, "reason": "fine"}

    result = evaluate(
        dataset=ITEMS[:1],
        task=answer,
        metrics=[metrics.hallucination, metrics.faithfulness],
        store=store,
    )

    assert result.polarity() == {"hallucination": False, "faithfulness": True}
    assert result.results[0].failed is True
