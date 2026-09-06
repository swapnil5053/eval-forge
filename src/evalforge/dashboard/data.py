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
from . import styles

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


# --- overview and traces -----------------------------------------------------


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
    """Bar rows carry their own width so the chart needs no scale of its own.

    Rows measuring zero are dropped: a spend panel listing four functions at
    $0.0000 is four lines with nothing in them to act on.
    """
    measured = [
        (row, row.tokens if measure == "tokens" else row.cost_usd) for row in rows
    ]
    measured = [(row, value) for row, value in measured if value]
    largest = max((value for _, value in measured), default=0)
    return [
        {
            "key": row.key,
            "value": f"{value:,}" if measure == "tokens" else f"${value:.4f}",
            "width": f"{(value / largest * 100):.1f}%",
        }
        for row, value in measured
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

    window = _trace_window(spans)

    def walk(span: queries.SpanRow, prefix: str, last: bool, depth: int) -> None:
        branch = "" if depth == 0 else f"{prefix}{'└─ ' if last else '├─ '}"
        rows.append(_span_row(span, branch, window))
        kids = children.get(span.id, [])
        extension = "" if depth == 0 else prefix + ("   " if last else "│  ")
        for index, child in enumerate(kids):
            walk(child, extension, index == len(kids) - 1, depth + 1)

    for index, root in enumerate(roots):
        walk(root, "", index == len(roots) - 1, 0)
    return rows


def _trace_window(spans: List[queries.SpanRow]) -> tuple:
    """(start, total_ms) for the trace, so each span can be placed on a shared axis."""
    starts = [span.start_time for span in spans if span.start_time is not None]
    if not starts:
        return None, 0.0
    start = min(starts)
    end_ms = max(
        (span.start_time - start).total_seconds() * 1000 + (span.latency_ms or 0.0)
        for span in spans
        if span.start_time is not None
    )
    return start, end_ms


def _offset_and_width(span: queries.SpanRow, window: tuple) -> tuple:
    start, total = window
    if start is None or not total or span.start_time is None:
        return "0%", "0%"
    offset = (span.start_time - start).total_seconds() * 1000
    width = max(span.latency_ms or 0.0, total * 0.004)
    return f"{offset / total * 100:.2f}%", f"{min(width, total - offset) / total * 100:.2f}%"


def _span_row(span: queries.SpanRow, branch: str, window: tuple = (None, 0.0)) -> Dict[str, Any]:
    tokens = ""
    if span.prompt_tokens or span.completion_tokens:
        tokens = f"{span.prompt_tokens or 0}/{span.completion_tokens or 0} tok"
    offset, width = _offset_and_width(span, window)
    return {
        "offset": offset,
        "width": width,
        "bar_colour": _span_colour(span),
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


def _span_colour(span: queries.SpanRow) -> str:
    """The LLM span carries the accent; an error carries red; everything else is dim."""
    if span.status == "error":
        return styles.ERROR
    if span.type == "llm":
        return styles.ACCENT
    return styles.BORDER_BRIGHT


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
    """The readout at the bottom of the sidebar: rows held and how fresh they are."""
    written = default_db_path().stat().st_mtime
    return {
        "traces": f"{store.count('traces'):,}",
        "updated": clock(
            datetime.datetime.fromtimestamp(written, datetime.timezone.utc)
        ),
    }


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


# --- formatting primitives ---------------------------------------------------


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


# --- experiments and datasets ------------------------------------------------


def experiment_rows(rows: List[queries.ExperimentRow]) -> List[Dict[str, Any]]:
    return [
        {
            "name": row.name,
            "dataset": row.dataset_name,
            "items": str(row.items),
            "errors": str(row.errors) if row.errors else "",
            "metrics": ", ".join(row.metrics) or EMPTY,
            "at": clock(row.created_at),
            "summary": " · ".join(
                f"{metric} {row.means[metric]:.2f}" for metric in row.metrics
            ) or EMPTY,
        }
        for row in rows
    ]


def metric_means(row: Optional[queries.ExperimentRow]) -> List[Dict[str, str]]:
    if row is None:
        return []
    return [
        {
            "metric": metric,
            "mean": f"{row.means[metric]:.3f}",
            "colour": styles.score_colour(row.means[metric], row.polarity.get(metric, True)),
            "direction": "higher is better" if row.polarity.get(metric, True) else "lower is better",
        }
        for metric in row.metrics
    ]


def experiment_item_rows(
    rows: List[queries.ExperimentItemRow], metrics: List[str], polarity: Dict[str, bool]
) -> List[Dict[str, Any]]:
    """One row per dataset item, with a cell per metric in a stable column order."""
    return [
        {
            "id": row.dataset_item_id[:8],
            "trace_id": (row.trace_id or "")[:8],
            "input": truncate(compact_json(row.input), 60) or EMPTY,
            "output": truncate(compact_json(row.output), 60) or EMPTY,
            "latency": milliseconds(row.latency_ms),
            "error": row.error or "",
            "has_error": bool(row.error),
            "cells": [_score_cell(row.scores.get(metric), polarity.get(metric, True))
                      for metric in metrics],
        }
        for row in rows
    ]


def _score_cell(score: Any, higher_is_better: bool) -> Dict[str, str]:
    if not isinstance(score, dict):
        return {"text": EMPTY, "colour": styles.TEXT_FAINT, "reason": ""}
    if "error" in score:
        return {"text": "err", "colour": styles.ERROR, "reason": str(score["error"])}
    value = float(score.get("value", 0.0))
    return {
        "text": f"{value:.2f}",
        "colour": styles.score_colour(value, score.get("higher_is_better", higher_is_better)),
        "reason": str(score.get("reason") or ""),
    }


def comparison_rows(rows: List[dict], left: str, right: str) -> List[Dict[str, Any]]:
    """Flatten a two-experiment comparison into one row per item and metric.

    The delta is the opened experiment minus the baseline it is being compared
    against, so a positive number means the run you opened moved that way - and the
    colour then reads it through the metric's own polarity.
    """
    flattened = []
    for row in rows:
        for metric, sides in sorted(row["metrics"].items()):
            opened, baseline = sides["left"], sides["right"]
            delta = None if opened is None or baseline is None else opened - baseline
            better = sides["higher_is_better"]
            flattened.append(
                {
                    "id": row["dataset_item_id"][:8],
                    "input": truncate(compact_json(row["input"]), 50) or EMPTY,
                    "metric": metric,
                    "left": EMPTY if opened is None else f"{opened:.2f}",
                    "right": EMPTY if baseline is None else f"{baseline:.2f}",
                    "delta": EMPTY if delta is None else f"{delta:+.2f}",
                    "colour": _delta_colour(delta, better),
                }
            )
    return flattened


def _delta_colour(delta: Optional[float], higher_is_better: bool) -> str:
    if delta is None or abs(delta) < 0.005:
        return styles.TEXT_DIM
    improved = delta > 0 if higher_is_better else delta < 0
    return styles.OK if improved else styles.ERROR


def dataset_rows(rows: List[queries.DatasetRow]) -> List[Dict[str, str]]:
    return [
        {
            "name": row.name,
            "description": row.description or EMPTY,
            "items": str(row.items),
            "at": clock(row.created_at),
        }
        for row in rows
    ]


def dataset_item_rows(rows: List[dict]) -> List[Dict[str, str]]:
    return [
        {
            "id": row["id"][:8],
            "input": truncate(compact_json(row["input"]), 90) or EMPTY,
            "expected": truncate(compact_json(row["expected_output"]), 50) or EMPTY,
        }
        for row in rows
    ]


# --- faithfulness audits -----------------------------------------------------


def audit_rows(rows: List[dict]) -> List[Dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "short_id": row["id"][:8],
            "trace_id": (row["trace_id"] or "")[:8],
            "query": truncate(row["query"] or "", 60) or EMPTY,
            "score": f"{row['score']:.2f}",
            "colour": styles.score_colour(row["score"]),
            "claims": str(row["claim_count"]),
            "unsupported": str(row["unsupported"]),
            "contradicted": str(row["contradicted"]),
            "at": clock(row["created_at"]),
        }
        for row in rows
    ]


def audit_claim_rows(audit: Any) -> List[Dict[str, Any]]:
    """Claims worst-first, each carrying its verdict colour and the evidence text."""
    ordered = sorted(audit.claims, key=lambda claim: claim.severity, reverse=True)
    return [
        {
            "claim": claim.claim,
            "verdict": claim.verdict,
            "colour": styles.VERDICT_COLOURS.get(claim.verdict, styles.TEXT_DIM),
            "rationale": claim.rationale or "",
            "evidence": " ".join(
                f"[{index}] {audit.context[index]}"
                for index in claim.evidence
                if 0 <= index < len(audit.context)
            ),
        }
        for claim in ordered
    ]


def audit_header(audit: Any) -> Dict[str, str]:
    return {
        "id": audit.id,
        "short_id": audit.id[:8],
        "trace_id": (audit.trace_id or "")[:8],
        "query": audit.query or EMPTY,
        "answer": audit.answer or EMPTY,
        "score": f"{audit.score:.2f}",
        "colour": styles.score_colour(audit.score),
        "claims": str(len(audit.claims)),
        "model": audit.model,
    }
