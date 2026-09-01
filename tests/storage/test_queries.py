import datetime

import pytest

from evalforge.storage import queries
from evalforge.storage.duckdb_store import Store

BASE = datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.timezone.utc)


def iso(offset_seconds):
    return (BASE + datetime.timedelta(seconds=offset_seconds)).isoformat()


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(queries, "since", lambda hours: BASE - datetime.timedelta(hours=1))
    with Store(tmp_path / "evalforge.db") as opened:
        _seed(opened)
        yield opened


def _seed(store):
    store.upsert("traces", 
        [
            {"id": "t1", "name": "rag", "start_time": iso(0), "end_time": iso(0.1), "status": "ok"},
            {"id": "t2", "name": "rag", "start_time": iso(10), "end_time": iso(12), "status": "ok"},
            {
                "id": "t3",
                "name": "summarise",
                "start_time": iso(20),
                "end_time": iso(20.5),
                "status": "error",
            },
        ]
    )
    store.upsert("spans", 
        [
            {
                "id": "s1",
                "trace_id": "t1",
                "name": "generate",
                "type": "llm",
                "start_time": iso(0),
                "end_time": iso(0.1),
                "status": "ok",
                "model": "gpt-4o-mini",
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "estimated_cost_usd": 0.001,
                "input": {"question": "capital of France"},
                "output": "Paris",
            },
            {
                "id": "s2",
                "trace_id": "t2",
                "name": "generate",
                "type": "llm",
                "start_time": iso(10),
                "end_time": iso(12),
                "status": "ok",
                "model": "claude-sonnet-4-5",
                "prompt_tokens": 400,
                "completion_tokens": 60,
                "estimated_cost_usd": 0.02,
                "output": "Tokyo",
            },
            {
                "id": "s3",
                "trace_id": "t2",
                "parent_span_id": "s2",
                "name": "retrieve",
                "type": "retrieval",
                "start_time": iso(10),
                "end_time": iso(10.4),
                "status": "ok",
            },
            {
                "id": "s4",
                "trace_id": "t3",
                "name": "summarise",
                "start_time": iso(20),
                "end_time": iso(20.5),
                "status": "error",
                "error": "Traceback\nValueError: empty document",
            },
        ]
    )


def test_summary(store):
    summary = queries.trace_summary(store)

    assert summary.traces == 3
    assert summary.errors == 1
    assert summary.error_rate == pytest.approx(1 / 3)
    assert summary.p50_latency_ms == pytest.approx(500)
    assert summary.p99_latency_ms == pytest.approx(2000, rel=0.05)
    assert summary.total_cost_usd == pytest.approx(0.021)
    assert (summary.prompt_tokens, summary.completion_tokens) == (500, 80)


def test_summary_of_an_empty_window(tmp_path):
    with Store(tmp_path / "empty.db") as store:
        summary = queries.trace_summary(store)
    assert summary.traces == 0
    assert summary.error_rate == 0.0
    assert summary.p95_latency_ms is None


def test_recent_traces_are_newest_first(store):
    rows = queries.recent_traces(store)
    assert [row.id for row in rows] == ["t3", "t2", "t1"]

    slowest = rows[1]
    assert slowest.span_count == 2
    assert slowest.latency_ms == pytest.approx(2000)
    assert slowest.tokens == 460
    assert slowest.cost_usd == pytest.approx(0.02)


def test_recent_traces_respects_limit(store):
    assert len(queries.recent_traces(store, limit=1)) == 1


def test_slow_traces(store):
    rows = queries.slow_traces(store, threshold_ms=400)
    assert [row.id for row in rows] == ["t2", "t3"]


def test_search_matches_span_input_and_output(store):
    assert [row.id for row in queries.search_traces(store, "capital of france")] == ["t1"]
    assert [row.id for row in queries.search_traces(store, "Tokyo")] == ["t2"]
    assert [row.id for row in queries.search_traces(store, "summarise")] == ["t3"]
    assert queries.search_traces(store, "nothing here") == []


def test_token_usage_by_model_ignores_spans_without_usage(store):
    rows = queries.token_usage(store)
    assert [(row.key, row.tokens) for row in rows] == [
        ("claude-sonnet-4-5", 460),
        ("gpt-4o-mini", 120),
    ]


def test_token_usage_by_function(store):
    rows = queries.token_usage(store, group_by="function")
    assert [row.key for row in rows] == ["generate"]
    assert rows[0].spans == 2


def test_cost_breakdown_includes_free_spans(store):
    rows = queries.cost_breakdown(store)
    assert [(row.key, round(row.cost_usd, 4)) for row in rows] == [
        ("generate", 0.021),
        ("retrieve", 0.0),
        ("summarise", 0.0),
    ]


def test_cost_breakdown_by_trace_name(store):
    rows = queries.cost_breakdown(store, group_by="trace")
    assert [row.key for row in rows] == ["rag", "summarise"]


def test_unknown_group_by_is_rejected(store):
    with pytest.raises(ValueError, match="group_by must be one of"):
        queries.token_usage(store, group_by="colour")


def test_trace_detail_by_prefix(store):
    row, spans = queries.trace_detail(store, "t2")

    assert row.id == "t2"
    assert [span.id for span in spans] == ["s2", "s3"]
    assert spans[1].parent_span_id == "s2"
    assert spans[0].output == "Tokyo"


def test_trace_detail_parses_json_columns(store):
    _, spans = queries.trace_detail(store, "t1")
    assert spans[0].input == {"question": "capital of France"}


def test_trace_detail_missing_id(store):
    assert queries.trace_detail(store, "nope") == (None, [])


def test_ambiguous_prefix_is_rejected(store):
    with pytest.raises(ValueError, match="more than one trace"):
        queries.trace_detail(store, "t")
