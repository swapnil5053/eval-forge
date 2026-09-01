"""Analytical queries over the trace store.

Every function takes a :class:`~evalforge.storage.duckdb_store.Store` and returns
dataclasses, so the CLI, the dashboard and the MCP server all read the same
numbers without any of them writing SQL.
"""

import dataclasses
import datetime
import json
from typing import Any, List, Optional, Tuple

from .duckdb_store import Store

GROUP_COLUMNS = {"model": "s.model", "function": "s.name", "trace": "t.name"}

_TRACE_SELECT = """
SELECT t.id,
       t.name,
       t.status,
       t.start_time,
       epoch_ms(t.end_time) - epoch_ms(t.start_time) AS latency_ms,
       count(s.id) AS span_count,
       coalesce(sum(s.estimated_cost_usd), 0) AS cost_usd,
       coalesce(sum(s.prompt_tokens), 0) + coalesce(sum(s.completion_tokens), 0) AS tokens
FROM traces t
LEFT JOIN spans s ON s.trace_id = t.id
"""


@dataclasses.dataclass
class TraceSummary:
    traces: int
    errors: int
    error_rate: float
    avg_latency_ms: Optional[float]
    p50_latency_ms: Optional[float]
    p95_latency_ms: Optional[float]
    p99_latency_ms: Optional[float]
    total_cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    since: datetime.datetime


@dataclasses.dataclass
class TraceRow:
    id: str
    name: str
    status: str
    start_time: datetime.datetime
    latency_ms: Optional[float]
    span_count: int
    cost_usd: float
    tokens: int


@dataclasses.dataclass
class SpanRow:
    id: str
    trace_id: str
    parent_span_id: Optional[str]
    name: str
    type: str
    status: str
    start_time: datetime.datetime
    latency_ms: Optional[float]
    input: Any
    output: Any
    error: Optional[str]
    model: Optional[str]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    cost_usd: Optional[float]


@dataclasses.dataclass
class GroupRow:
    key: str
    spans: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def since(hours: float) -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)


def trace_summary(store: Store, hours: float = 24) -> TraceSummary:
    """Volume, latency percentiles, error rate and spend over a time window."""
    cutoff = since(hours)
    traces, errors, avg_ms, p50, p95, p99 = store.db.execute(
        """
        WITH windowed AS (
            SELECT status, epoch_ms(end_time) - epoch_ms(start_time) AS latency_ms
            FROM traces
            WHERE start_time >= ?
        )
        SELECT count(*),
               count(*) FILTER (WHERE status = 'error'),
               avg(latency_ms),
               quantile_cont(latency_ms, 0.5),
               quantile_cont(latency_ms, 0.95),
               quantile_cont(latency_ms, 0.99)
        FROM windowed
        """,
        [cutoff],
    ).fetchone()

    cost, prompt_tokens, completion_tokens = store.db.execute(
        """
        SELECT coalesce(sum(estimated_cost_usd), 0),
               coalesce(sum(prompt_tokens), 0),
               coalesce(sum(completion_tokens), 0)
        FROM spans
        WHERE start_time >= ?
        """,
        [cutoff],
    ).fetchone()

    return TraceSummary(
        traces=traces,
        errors=errors,
        error_rate=errors / traces if traces else 0.0,
        avg_latency_ms=avg_ms,
        p50_latency_ms=p50,
        p95_latency_ms=p95,
        p99_latency_ms=p99,
        total_cost_usd=float(cost),
        prompt_tokens=int(prompt_tokens),
        completion_tokens=int(completion_tokens),
        since=cutoff,
    )


def recent_traces(store: Store, limit: int = 20, hours: Optional[float] = None) -> List[TraceRow]:
    where, parameters = ("WHERE t.start_time >= ?", [since(hours)]) if hours else ("", [])
    rows = store.db.execute(
        f"{_TRACE_SELECT} {where} GROUP BY ALL ORDER BY t.start_time DESC LIMIT ?",
        parameters + [limit],
    ).fetchall()
    return [_trace_row(row) for row in rows]


def slow_traces(store: Store, threshold_ms: float, limit: int = 20) -> List[TraceRow]:
    """Traces slower than a threshold, slowest first."""
    rows = store.db.execute(
        f"""{_TRACE_SELECT}
        GROUP BY ALL
        HAVING epoch_ms(t.end_time) - epoch_ms(t.start_time) >= ?
        ORDER BY latency_ms DESC
        LIMIT ?
        """,
        [threshold_ms, limit],
    ).fetchall()
    return [_trace_row(row) for row in rows]


def search_traces(store: Store, query: str, limit: int = 50) -> List[TraceRow]:
    """Case-insensitive substring search over trace and span names, inputs and outputs.

    Substring rather than a real inverted index on purpose: DuckDB's FTS extension
    is downloaded on first use, and an offline-first tool should not need the
    network to find a trace.
    """
    pattern = f"%{query}%"
    rows = store.db.execute(
        f"""{_TRACE_SELECT}
        WHERE t.name ILIKE ?
           OR t.id IN (
                SELECT trace_id FROM spans
                WHERE name ILIKE ?
                   OR CAST(input AS VARCHAR) ILIKE ?
                   OR CAST(output AS VARCHAR) ILIKE ?
           )
        GROUP BY ALL
        ORDER BY t.start_time DESC
        LIMIT ?
        """,
        [pattern, pattern, pattern, pattern, limit],
    ).fetchall()
    return [_trace_row(row) for row in rows]


def trace_detail(store: Store, trace_id: str) -> Tuple[Optional[TraceRow], List[SpanRow]]:
    """One trace and its spans. ``trace_id`` may be an unambiguous id prefix."""
    row = store.db.execute(
        f"{_TRACE_SELECT} WHERE t.id LIKE ? GROUP BY ALL LIMIT 2", [f"{trace_id}%"]
    ).fetchall()
    if not row:
        return None, []
    if len(row) > 1:
        raise ValueError(f"trace id prefix {trace_id!r} matches more than one trace")

    spans = store.db.execute(
        """
        SELECT id, trace_id, parent_span_id, name, type, status, start_time,
               epoch_ms(end_time) - epoch_ms(start_time) AS latency_ms,
               input, output, error, model, prompt_tokens, completion_tokens,
               estimated_cost_usd
        FROM spans
        WHERE trace_id = ?
        ORDER BY start_time
        """,
        [row[0][0]],
    ).fetchall()
    return _trace_row(row[0]), [_span_row(span) for span in spans]


def token_usage(store: Store, hours: float = 24, group_by: str = "model") -> List[GroupRow]:
    """Token totals per model, function or trace. Spans without usage are excluded."""
    return _grouped(store, hours, group_by, order="tokens", with_usage_only=True)


def cost_breakdown(store: Store, hours: float = 24, group_by: str = "function") -> List[GroupRow]:
    """Spend per function, model or trace, including the spans that cost nothing."""
    return _grouped(store, hours, group_by, order="cost")


def _grouped(
    store: Store,
    hours: float,
    group_by: str,
    order: str,
    with_usage_only: bool = False,
) -> List[GroupRow]:
    column = GROUP_COLUMNS.get(group_by)
    if column is None:
        raise ValueError(
            f"group_by must be one of {sorted(GROUP_COLUMNS)}, got {group_by!r}"
        )
    order_column = (
        "coalesce(sum(s.estimated_cost_usd), 0)"
        if order == "cost"
        else "coalesce(sum(s.prompt_tokens), 0) + coalesce(sum(s.completion_tokens), 0)"
    )

    rows = store.db.execute(
        """
        SELECT coalesce({column}, '(unknown)') AS key,
               count(*) AS spans,
               coalesce(sum(s.prompt_tokens), 0) AS prompt_tokens,
               coalesce(sum(s.completion_tokens), 0) AS completion_tokens,
               coalesce(sum(s.estimated_cost_usd), 0) AS cost_usd
        FROM spans s
        LEFT JOIN traces t ON t.id = s.trace_id
        WHERE s.start_time >= ? {usage_filter}
        GROUP BY ALL
        ORDER BY {order_column} DESC, key
        """.format(
            column=column,
            usage_filter=(
                "AND (s.prompt_tokens IS NOT NULL OR s.completion_tokens IS NOT NULL)"
                if with_usage_only
                else ""
            ),
            order_column=order_column,
        ),
        [since(hours)],
    ).fetchall()
    return [
        GroupRow(
            key=key,
            spans=spans,
            prompt_tokens=int(prompt_tokens),
            completion_tokens=int(completion_tokens),
            cost_usd=float(cost),
        )
        for key, spans, prompt_tokens, completion_tokens, cost in rows
    ]


def _trace_row(row: tuple) -> TraceRow:
    return TraceRow(
        id=row[0],
        name=row[1],
        status=row[2],
        start_time=row[3],
        latency_ms=row[4],
        span_count=row[5],
        cost_usd=float(row[6]),
        tokens=int(row[7]),
    )


def _span_row(row: tuple) -> SpanRow:
    return SpanRow(
        id=row[0],
        trace_id=row[1],
        parent_span_id=row[2],
        name=row[3],
        type=row[4],
        status=row[5],
        start_time=row[6],
        latency_ms=row[7],
        input=_load_json(row[8]),
        output=_load_json(row[9]),
        error=row[10],
        model=row[11],
        prompt_tokens=row[12],
        completion_tokens=row[13],
        cost_usd=row[14],
    )


def _load_json(value: Optional[str]) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value
