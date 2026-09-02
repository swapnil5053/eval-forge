"""Reads for the dashboard, formatted for display.

The dashboard opens DuckDB read-only and never writes: evaluation and ingestion hold
the write lock, and a viewer must not compete with them. Everything here returns
plain dicts of already-formatted strings, so the components stay dumb and the
formatting is testable without starting a browser.
"""

import datetime
import json
import logging
import re
from typing import Any, Dict, List, Optional

from ..storage import queries
from ..storage.duckdb_store import Store, default_db_path

LOGGER = logging.getLogger(__name__)

EMPTY = "—"
PAGE_SIZE = 50

EMPTY_SUMMARY = {
    "traces": EMPTY,
    "avg_latency": EMPTY,
    "p95_latency": EMPTY,
    "error_rate": EMPTY,
    "cost": EMPTY,
    "error_rate_high": False,
}


def database_exists() -> bool:
    return default_db_path().exists()


def read_only_store() -> Store:
    return Store(default_db_path(), read_only=True)


def summary(store: Store, hours: float = 24) -> Dict[str, Any]:
    row = queries.trace_summary(store, hours=hours)
    if not row.traces:
        return dict(EMPTY_SUMMARY)
    return {
        "traces": f"{row.traces:,}",
        "avg_latency": milliseconds(row.avg_latency_ms),
        "p95_latency": milliseconds(row.p95_latency_ms),
        "error_rate": f"{row.error_rate * 100:.1f}",
        "cost": f"{row.total_cost_usd:.4f}",
        "error_rate_high": row.error_rate > 0.05,
    }


def volume_series(points: List[queries.SeriesPoint]) -> List[Dict[str, Any]]:
    return [{"day": point.day.strftime("%m-%d"), "traces": point.traces} for point in points]


def latency_series(points: List[queries.SeriesPoint]) -> List[Dict[str, Any]]:
    return [
        {
            "day": point.day.strftime("%m-%d"),
            "p50": round(point.p50_latency_ms or 0, 1),
            "p95": round(point.p95_latency_ms or 0, 1),
            "p99": round(point.p99_latency_ms or 0, 1),
        }
        for point in points
    ]


def group_rows(rows: List[queries.GroupRow], measure: str) -> List[Dict[str, Any]]:
    """Bar rows carry their own width so the chart needs no scale of its own."""
    values = [row.tokens if measure == "tokens" else row.cost_usd for row in rows]
    largest = max(values, default=0)
    return [
        {
            "key": row.key,
            "value": f"{value:,}" if measure == "tokens" else f"${value:.4f}",
            "width": f"{(value / largest * 100) if largest else 0:.1f}%",
        }
        for row, value in zip(rows, values)
    ]


def error_rows(rows: List[queries.ErrorRow]) -> List[Dict[str, str]]:
    return [
        {
            "trace_id": row.trace_id,
            "short_id": row.trace_id[:8],
            "at": clock(row.start_time),
            "span_name": row.span_name,
            "message": truncate(row.message, 110),
        }
        for row in rows
    ]


def trace_rows(rows: List[queries.TraceRow]) -> List[Dict[str, Any]]:
    return [
        {
            "id": row.id,
            "short_id": row.id[:8],
            "at": clock(row.start_time),
            "name": row.name,
            "status": row.status,
            "is_error": row.status == "error",
            "spans": str(row.span_count),
            "latency": milliseconds(row.latency_ms),
            "tokens": f"{row.tokens:,}" if row.tokens else EMPTY,
            "cost": money(row.cost_usd),
        }
        for row in rows
    ]


def span_tree(spans: List[queries.SpanRow]) -> List[Dict[str, Any]]:
    """Flatten the span tree into rows carrying their own indent guides.

    Each row keeps the ``tree(1)`` prefix it should render with, so the component
    prints text instead of nesting boxes.
    """
    children: Dict[Optional[str], List[queries.SpanRow]] = {}
    for span in spans:
        children.setdefault(span.parent_span_id, []).append(span)

    known = {span.id for span in spans}
    roots = [span for span in spans if span.parent_span_id not in known]
    rows: List[Dict[str, Any]] = []

    def walk(span: queries.SpanRow, prefix: str, last: bool, depth: int) -> None:
        branch = "" if depth == 0 else f"{prefix}{'└─ ' if last else '├─ '}"
        rows.append(_span_row(span, branch))
        kids = children.get(span.id, [])
        extension = "" if depth == 0 else prefix + ("   " if last else "│  ")
        for index, child in enumerate(kids):
            walk(child, extension, index == len(kids) - 1, depth + 1)

    for index, root in enumerate(roots):
        walk(root, "", index == len(roots) - 1, 0)
    return rows


def _span_row(span: queries.SpanRow, branch: str) -> Dict[str, Any]:
    tokens = ""
    if span.prompt_tokens or span.completion_tokens:
        tokens = f"{span.prompt_tokens or 0}/{span.completion_tokens or 0} tok"
    return {
        "id": span.id,
        "branch": branch,
        "name": span.name,
        "type": span.type,
        "status": span.status,
        "is_error": span.status == "error",
        "latency": milliseconds(span.latency_ms),
        "tokens": tokens,
        "cost": money(span.cost_usd),
        "model": span.model or "",
        "input": pretty_json(span.input),
        "output": pretty_json(span.output),
        "input_preview": truncate(compact_json(span.input), 80) or EMPTY,
        "output_preview": truncate(compact_json(span.output), 80) or EMPTY,
        "error": (span.error or "").strip(),
        "has_error": bool(span.error),
    }


def attribution_row(store: Store, span_id: str) -> List[Dict[str, str]]:
    """Token highlighting for a span, empty when nothing has been attributed yet."""
    from ..eval.attribution import for_span

    found = for_span(store, span_id)
    if found is None:
        return []
    return [
        {"token": token, "weight": f"{weight:.3f}", "opacity": f"{0.15 + 0.85 * abs(weight):.2f}"}
        for token, weight in zip(found.tokens, found.normalised())
    ]


def footer(store: Store) -> Dict[str, str]:
    """The readout at the bottom of the sidebar: rows held, freshness, file size."""
    path = default_db_path()
    stat = path.stat()
    return {
        "traces": f"{store.count('traces'):,}",
        "updated": clock(
            datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc)
        ),
        "size": megabytes(stat.st_size),
    }


def megabytes(size: int) -> str:
    return f"{size / 1024:.0f}K" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f}M"


# Keys, strings, numbers and literals, in that order of preference.
_JSON_TOKEN = re.compile(
    r'("(?:\\.|[^"\\])*")\s*:|("(?:\\.|[^"\\])*")|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)'
    r'|\b(true|false|null)\b'
)
_KINDS = ("key", "string", "number", "literal")


def json_parts(text: str) -> List[Dict[str, str]]:
    """Split JSON into coloured runs so the viewer can highlight without a library."""
    parts: List[Dict[str, str]] = []
    position = 0
    for match in _JSON_TOKEN.finditer(text or ""):
        index = next(i for i, group in enumerate(match.groups()) if group is not None)
        start = match.start(index + 1)
        if start > position:
            parts.append({"text": text[position:start], "kind": "plain"})
        parts.append({"text": match.group(index + 1), "kind": _KINDS[index]})
        position = match.end(index + 1)
    if position < len(text or ""):
        parts.append({"text": text[position:], "kind": "plain"})
    return parts


def milliseconds(latency: Optional[float]) -> str:
    if latency is None:
        return EMPTY
    return f"{latency:.0f}ms" if latency < 1000 else f"{latency / 1000:.2f}s"


def money(usd: Optional[float]) -> str:
    if not usd:
        return EMPTY
    return f"${usd:.6f}" if usd < 0.01 else f"${usd:.4f}"


def clock(moment: Optional[datetime.datetime]) -> str:
    if moment is None:
        return EMPTY
    return moment.astimezone().strftime("%m-%d %H:%M:%S")


def truncate(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else f"{text[:limit]}…"


def pretty_json(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, default=str)


def compact_json(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)
