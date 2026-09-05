import asyncio
import datetime
import json

import pytest

pytest.importorskip("mcp")

from evalforge.mcp import server  # noqa: E402
from evalforge.storage.duckdb_store import Store  # noqa: E402

BASE = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALFORGE_HOME", str(tmp_path))
    path = tmp_path / "evalforge.db"
    with Store(path) as store:
        store.upsert("traces", [
            {"id": "t1", "name": "rag", "start_time": BASE,
             "end_time": BASE + datetime.timedelta(milliseconds=300), "status": "ok"},
        ])
        store.upsert("spans", [
            {"id": "s1", "trace_id": "t1", "name": "generate", "type": "llm",
             "start_time": BASE, "end_time": BASE + datetime.timedelta(milliseconds=300),
             "status": "ok", "model": "gpt-4o-mini", "prompt_tokens": 100,
             "completion_tokens": 20, "estimated_cost_usd": 0.001,
             "input": {"question": "capital of France"}, "output": "Paris."},
        ])
        store.upsert("datasets", [{"id": "d1", "name": "capitals", "created_at": BASE}])
        store.upsert("experiments", [
            {"id": "e1", "name": "v1", "dataset_id": "d1", "created_at": BASE}])
        store.upsert("experiment_results", [
            {"id": "r1", "experiment_id": "e1", "dataset_item_id": "i1", "output": "Paris.",
             "latency_ms": 120.0, "created_at": BASE,
             "scores": {"faithfulness": {"value": 0.8, "higher_is_better": True}}}])
    return tmp_path


def call(name, arguments=None):
    """Invoke a tool and hand back the structured payload a client would receive."""
    result = asyncio.run(server.build().call_tool(name, arguments or {}))
    structured = getattr(result, "structuredContent", None) or getattr(
        result, "structured_content", None
    )
    if structured is None:
        return json.loads(result.content[0].text)
    # A tool returning a list arrives wrapped as {"result": [...]}.
    return structured["result"] if set(structured) == {"result"} else structured


def test_every_tool_and_resource_is_registered(home):
    built = server.build()
    tools = asyncio.run(built.list_tools())
    resources = asyncio.run(built.list_resources())

    assert sorted(tool.name for tool in tools) == [
        "get_experiment",
        "get_trace",
        "get_trace_stats",
        "list_experiments",
        "list_traces",
        "run_faithfulness_audit",
        "search_traces",
    ]
    assert sorted(str(resource.uri) for resource in resources) == [
        "evalforge://stats",
        "evalforge://traces/latest",
    ]


def test_every_tool_is_documented(home):
    tools = asyncio.run(server.build().list_tools())
    assert all(tool.description for tool in tools)


def test_trace_stats(home):
    stats = call("get_trace_stats", {"hours": 24})
    assert stats["traces"] == 1
    assert stats["prompt_tokens"] == 100
    assert stats["total_cost_usd"] == pytest.approx(0.001)


def test_get_trace_returns_spans(home):
    payload = call("get_trace", {"trace_id": "t1"})
    assert payload["trace"]["name"] == "rag"
    assert payload["spans"][0]["model"] == "gpt-4o-mini"
    assert payload["spans"][0]["input"] == {"question": "capital of France"}


def test_search_traces(home):
    assert len(call("search_traces", {"query": "capital"})) == 1
    assert call("search_traces", {"query": "zzz"}) == []


def test_experiments(home):
    listed = call("list_experiments")
    assert listed[0]["name"] == "v1"
    assert listed[0]["means"] == {"faithfulness": 0.8}

    detail = call("get_experiment", {"name": "v1"})
    assert detail["items"][0]["output"] == "Paris."


def test_a_missing_database_says_what_to_run(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALFORGE_HOME", str(tmp_path / "empty"))
    with pytest.raises(server.StoreUnavailable, match="evalforge init"):
        server._reader()


def test_the_reader_is_read_only(home):
    with server._reader() as store:
        assert store.read_only is True
