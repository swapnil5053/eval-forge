import asyncio
from dataclasses import dataclass

import pytest

from evalforge import trace


def records_by_type(records, record_type):
    return [record for record in records if record["type"] == record_type]


def test_captures_input_output_and_latency(read_spool):
    @trace
    def add(left, right=2):
        return left + right

    assert add(1) == 3

    spans = records_by_type(read_spool(), "span_end")
    assert len(spans) == 1
    assert spans[0]["input"] == {"left": 1, "right": 2}
    assert spans[0]["output"] == 3
    assert spans[0]["status"] == "ok"
    assert spans[0]["end_time"] > spans[0]["start_time"]


def test_named_and_tagged(read_spool):
    @trace(name="retrieval-step", type="retrieval", tags={"stage": "recall"})
    def retrieve(query):
        return ["doc"]

    retrieve("q")

    span = records_by_type(read_spool(), "span_end")[0]
    assert span["name"] == "retrieval-step"
    assert span["span_type"] == "retrieval"
    assert span["tags"] == {"stage": "recall"}


def test_nested_calls_build_a_tree(read_spool):
    @trace
    def child():
        return "c"

    @trace
    def parent():
        return child()

    parent()
    records = read_spool()

    spans = {span["name"]: span for span in records_by_type(records, "span_end")}
    assert "parent_span_id" not in spans["parent"]
    assert spans["child"]["parent_span_id"] == spans["parent"]["id"]
    assert spans["child"]["trace_id"] == spans["parent"]["trace_id"]

    assert len(records_by_type(records, "trace_start")) == 1
    assert len(records_by_type(records, "trace_end")) == 1


def test_sibling_calls_are_separate_traces(read_spool):
    @trace
    def unit():
        return 1

    unit()
    unit()

    traces = {span["trace_id"] for span in records_by_type(read_spool(), "span_end")}
    assert len(traces) == 2


def test_error_is_recorded_and_reraised(read_spool):
    @trace
    def boom():
        raise ValueError("no")

    with pytest.raises(ValueError, match="no"):
        boom()

    records = read_spool()
    span = records_by_type(records, "span_end")[0]
    assert span["status"] == "error"
    assert "ValueError: no" in span["error"]
    assert records_by_type(records, "trace_end")[0]["status"] == "error"


def test_error_in_child_does_not_orphan_the_stack(read_spool):
    @trace
    def child():
        raise RuntimeError("inner")

    @trace
    def parent():
        try:
            child()
        except RuntimeError:
            return "recovered"

    assert parent() == "recovered"

    spans = {span["name"]: span for span in records_by_type(read_spool(), "span_end")}
    assert spans["parent"]["status"] == "ok"
    assert spans["child"]["status"] == "error"
    assert spans["child"]["parent_span_id"] == spans["parent"]["id"]


def test_async_functions(read_spool):
    @trace
    async def fetch(url):
        await asyncio.sleep(0)
        return f"body:{url}"

    @trace
    async def pipeline():
        return await fetch("/a")

    assert asyncio.run(pipeline()) == "body:/a"

    spans = {span["name"]: span for span in records_by_type(read_spool(), "span_end")}
    assert spans["fetch"]["parent_span_id"] == spans["pipeline"]["id"]


def test_concurrent_async_tasks_do_not_share_a_parent(read_spool):
    @trace
    async def leaf(index):
        await asyncio.sleep(0.01 if index == 0 else 0)
        return index

    async def main():
        return await asyncio.gather(leaf(0), leaf(1))

    asyncio.run(main())

    spans = records_by_type(read_spool(), "span_end")
    assert len(spans) == 2
    assert all("parent_span_id" not in span for span in spans)
    assert len({span["trace_id"] for span in spans}) == 2


@dataclass
class _Usage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class _Response:
    model: str
    usage: _Usage


def test_extracts_token_usage_from_object(read_spool):
    @trace
    def call():
        return _Response(model="gpt-4o-mini", usage=_Usage(120, 30))

    call()

    span = records_by_type(read_spool(), "span_end")[0]
    assert span["span_type"] == "llm"
    assert span["model"] == "gpt-4o-mini"
    assert span["prompt_tokens"] == 120
    assert span["completion_tokens"] == 30


def test_extracts_token_usage_from_dict(read_spool):
    @trace
    def call():
        return {
            "model": "claude-3-5-sonnet-20240620",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    call()

    span = records_by_type(read_spool(), "span_end")[0]
    assert span["prompt_tokens"] == 10
    assert span["completion_tokens"] == 5


def test_output_without_usage_stays_general(read_spool):
    @trace
    def call():
        return {"model": "gpt-4o", "text": "hi"}

    call()

    span = records_by_type(read_spool(), "span_end")[0]
    assert span["span_type"] == "general"
    assert "prompt_tokens" not in span


def test_capture_can_be_disabled(read_spool):
    @trace(capture_input=False, capture_output=False)
    def secret(password):
        return password

    secret("hunter2")

    span = records_by_type(read_spool(), "span_end")[0]
    assert "input" not in span
    assert "output" not in span


def test_unserializable_values_do_not_break_tracing(read_spool):
    class Opaque:
        __slots__ = ()

    @trace
    def call(thing):
        return thing

    call(Opaque())

    span = records_by_type(read_spool(), "span_end")[0]
    assert "Opaque" in span["input"]["thing"]


def test_methods_drop_self_from_input(read_spool):
    class Pipeline:
        @trace
        def run(self, query):
            return query

    Pipeline().run("q")

    span = records_by_type(read_spool(), "span_end")[0]
    assert span["input"] == {"query": "q"}
    assert span["name"].endswith("Pipeline.run")


def test_passed_through_response_is_priced_once(read_spool):
    @trace
    def call():
        return {"model": "gpt-4o", "usage": {"prompt_tokens": 100, "completion_tokens": 10}}

    @trace
    def wrapper():
        return call()

    wrapper()

    spans = {span["name"]: span for span in records_by_type(read_spool(), "span_end")}
    assert spans["call"]["prompt_tokens"] == 100
    assert "prompt_tokens" not in spans["wrapper"]
    assert spans["wrapper"]["span_type"] == "general"
