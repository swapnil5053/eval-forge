import datetime

import pytest

from evalforge.dashboard import data
from evalforge.storage import queries
from evalforge.storage.duckdb_store import Store

BASE = datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.timezone.utc)


def span(identifier, parent, name, span_type="general", **overrides):
    fields = {
        "id": identifier,
        "trace_id": "t1",
        "parent_span_id": parent,
        "name": name,
        "type": span_type,
        "status": "ok",
        "start_time": BASE,
        "latency_ms": 12.0,
        "input": None,
        "output": None,
        "error": None,
        "model": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "cost_usd": None,
    }
    fields.update(overrides)
    return queries.SpanRow(**fields)


def test_span_tree_draws_connectors():
    rows = data.span_tree(
        [
            span("root", None, "rag"),
            span("a", "root", "retrieve"),
            span("b", "root", "generate"),
            span("c", "b", "rerank"),
        ]
    )

    assert [(row["name"], row["branch"]) for row in rows] == [
        ("rag", ""),
        ("retrieve", "├─ "),
        ("generate", "└─ "),
        ("rerank", "   └─ "),
    ]


def test_span_tree_keeps_the_guide_through_deep_branches():
    rows = data.span_tree(
        [
            span("root", None, "rag"),
            span("a", "root", "first"),
            span("a1", "a", "nested"),
            span("b", "root", "second"),
        ]
    )
    assert [row["branch"] for row in rows] == ["", "├─ ", "│  └─ ", "└─ "]


def test_span_tree_treats_an_unknown_parent_as_a_root():
    rows = data.span_tree([span("orphan", "vanished", "leftover")])
    assert [row["branch"] for row in rows] == [""]


def test_span_row_formatting():
    row = data.span_tree(
        [
            span(
                "s1",
                None,
                "generate",
                "llm",
                model="gpt-4o-mini",
                prompt_tokens=120,
                completion_tokens=30,
                cost_usd=0.0004,
                input={"question": "capital?"},
                output="Paris.",
                status="error",
                error="  Traceback\nValueError: no  ",
            )
        ]
    )[0]

    assert row["tokens"] == "120/30 tok"
    assert row["cost"] == "$0.000400"
    assert row["is_error"] is True
    assert row["error"] == "Traceback\nValueError: no"
    assert row["input_preview"] == '{"question": "capital?"}'
    assert row["output"] == "Paris."


def test_a_span_with_no_output_previews_as_a_dash():
    assert data.span_tree([span("s1", None, "noop")])[0]["output_preview"] == data.EMPTY


def test_json_parts_labels_each_run():
    parts = data.json_parts('{"n": 42, "ok": true, "s": "x"}')
    kinds = {part["kind"] for part in parts}

    assert kinds == {"plain", "key", "number", "literal", "string"}
    assert "".join(part["text"] for part in parts) == '{"n": 42, "ok": true, "s": "x"}'


def test_json_parts_of_plain_text():
    assert data.json_parts("not json") == [{"text": "not json", "kind": "plain"}]


def test_group_rows_scale_to_the_largest():
    rows = [
        queries.GroupRow(key="a", spans=1, prompt_tokens=80, completion_tokens=20, cost_usd=0.5),
        queries.GroupRow(key="b", spans=1, prompt_tokens=20, completion_tokens=5, cost_usd=0.1),
    ]

    assert [row["width"] for row in data.group_rows(rows, "tokens")] == ["100.0%", "25.0%"]
    assert data.group_rows(rows, "cost")[1]["value"] == "$0.1000"


def test_group_rows_when_everything_is_zero():
    rows = [queries.GroupRow(key="a", spans=1, prompt_tokens=0, completion_tokens=0, cost_usd=0)]
    assert data.group_rows(rows, "tokens")[0]["width"] == "0.0%"


def test_error_rows_show_only_the_exception_line():
    rows = data.error_rows(
        [
            queries.ErrorRow(
                trace_id="abcdef1234",
                span_name="generate",
                start_time=BASE,
                message="LookupError: no context retrieved",
            )
        ]
    )
    assert rows[0]["short_id"] == "abcdef12"
    assert rows[0]["message"] == "LookupError: no context retrieved"


def test_formatters():
    assert data.milliseconds(None) == data.EMPTY
    assert data.milliseconds(940) == "940ms"
    assert data.milliseconds(1500) == "1.50s"
    assert data.money(None) == data.EMPTY
    assert data.money(0.5) == "$0.5000"
    assert data.money(0.0001) == "$0.000100"
    assert data.truncate("a  b   c", 80) == "a b c"
    assert data.truncate("abcdef", 3) == "abc…"
    assert data.megabytes(2048) == "2K"
    assert data.megabytes(5 * 1024 * 1024) == "5.0M"


def test_summary_of_an_empty_database(tmp_path):
    with Store(tmp_path / "evalforge.db") as store:
        assert data.summary(store) == data.EMPTY_SUMMARY


def test_summary_formats_and_flags_a_high_error_rate(tmp_path):
    with Store(tmp_path / "evalforge.db") as store:
        store.upsert(
            "traces",
            [
                {"id": "t1", "name": "a", "start_time": BASE, "end_time": BASE, "status": "ok"},
                {"id": "t2", "name": "a", "start_time": BASE, "end_time": BASE, "status": "error"},
            ],
        )
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(queries, "since", lambda hours: BASE - datetime.timedelta(hours=1))
            summary = data.summary(store)

    assert summary["traces"] == "2"
    assert summary["error_rate"] == "50.0"
    assert summary["error_rate_high"] is True
