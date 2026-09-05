import datetime

import pytest

from evalforge.dashboard import data, styles
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


def comparison_input(left_value, right_value, higher_is_better=True):
    return [
        {
            "dataset_item_id": "item0",
            "input": {"question": "q"},
            "metrics": {
                "faithfulness": {
                    "left": left_value,
                    "right": right_value,
                    "higher_is_better": higher_is_better,
                }
            },
        }
    ]


def test_delta_is_the_opened_run_minus_its_baseline():
    row = data.comparison_rows(comparison_input(0.84, 0.45), "v2", "v1")[0]

    assert row["left"] == "0.84"
    assert row["right"] == "0.45"
    assert row["delta"] == "+0.39"
    assert row["colour"] == styles.OK


def test_a_regression_on_a_higher_is_better_metric_reads_red():
    row = data.comparison_rows(comparison_input(0.40, 0.80), "v2", "v1")[0]
    assert row["delta"] == "-0.40"
    assert row["colour"] == styles.ERROR


def test_polarity_flips_which_direction_is_good():
    improved = data.comparison_rows(comparison_input(0.18, 0.55, False), "v2", "v1")[0]
    worsened = data.comparison_rows(comparison_input(0.55, 0.18, False), "v2", "v1")[0]

    assert improved["delta"] == "-0.37"
    assert improved["colour"] == styles.OK
    assert worsened["colour"] == styles.ERROR


def test_a_missing_side_has_no_delta():
    row = data.comparison_rows(comparison_input(0.5, None), "v2", "v1")[0]
    assert row["right"] == data.EMPTY
    assert row["delta"] == data.EMPTY
    assert row["colour"] == styles.TEXT_DIM


def test_an_unchanged_score_is_neutral():
    row = data.comparison_rows(comparison_input(0.5, 0.5), "v2", "v1")[0]
    assert row["colour"] == styles.TEXT_DIM


def test_experiment_rows_summarise_their_means():
    row = queries.ExperimentRow(
        id="e1", name="v1", dataset_name="capitals", items=2, errors=1,
        created_at=BASE, means={"faithfulness": 0.75, "hallucination": 0.2},
        polarity={"faithfulness": True, "hallucination": False},
    )
    formatted = data.experiment_rows([row])[0]

    assert formatted["summary"] == "faithfulness 0.75 · hallucination 0.20"
    assert formatted["errors"] == "1"

    means = data.metric_means(row)
    assert [entry["direction"] for entry in means] == ["higher is better", "lower is better"]
    assert means[0]["colour"] == styles.WARN
    assert means[1]["colour"] == styles.OK


def test_waterfall_places_spans_on_a_shared_axis():
    start = BASE
    rows = data.span_tree(
        [
            span("root", None, "rag", start_time=start, latency_ms=1000.0),
            span("a", "root", "retrieve", start_time=start, latency_ms=250.0),
            span(
                "b", "root", "generate", "llm",
                start_time=start + datetime.timedelta(milliseconds=250), latency_ms=750.0,
            ),
        ]
    )

    assert rows[0]["offset"] == "0.00%"
    assert rows[0]["width"] == "100.00%"
    assert rows[1]["width"] == "25.00%"
    assert rows[2]["offset"] == "25.00%"
    assert rows[2]["bar_colour"] == styles.ACCENT


def test_an_errored_span_bar_is_red():
    rows = data.span_tree([span("s1", None, "boom", status="error", latency_ms=5.0)])
    assert rows[0]["bar_colour"] == styles.ERROR
