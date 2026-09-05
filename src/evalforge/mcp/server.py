"""An MCP server over the local trace store.

Opik ships an MCP server too, and this is not a novel idea. The difference is
architectural: theirs talks to a running Java backend over HTTP, so it needs a
server, an API key and a workspace. This one opens the DuckDB file directly, which
means nothing to start and nothing to authenticate - and it can expose the
faithfulness audit, which has no upstream equivalent.

Reads use a read-only connection, so asking questions from an assistant never
competes with ingestion or an evaluation for the write lock.
"""

import logging
from typing import Any, Dict, List, Optional

from ..eval import faithfulness_audit
from ..eval.judge import DEFAULT_MODEL
from ..storage import queries
from ..storage.duckdb_store import DatabaseLocked, Store, default_db_path

LOGGER = logging.getLogger(__name__)

SERVER_NAME = "evalforge"
INSTRUCTIONS = """Query a local EvalForge trace store: LLM traces, spans, costs,
experiments and claim-level faithfulness audits. All data is read from a DuckDB
file on this machine."""


class StoreUnavailable(RuntimeError):
    """There is no database to read yet."""


def _server_class():
    """The decorator-style server class, whichever major version of mcp is installed.

    mcp 2.0 renamed FastMCP to MCPServer and moved it; the surface this module uses
    (tool, resource, run) is identical either way, so one import shim covers both.
    """
    try:
        from mcp.server.mcpserver import MCPServer

        return MCPServer
    except ImportError:
        pass
    try:
        from mcp.server.fastmcp import FastMCP

        return FastMCP
    except ImportError as error:
        raise ImportError(
            "the MCP server needs the mcp package (this looks like a version it does "
            "not recognise if mcp is already installed). Install or upgrade it with "
            "'pip install -U evalforge[mcp]'."
        ) from error


def build():
    """Create the MCP server. Imported lazily so `mcp` stays an optional dependency."""
    server = _server_class()(SERVER_NAME, instructions=INSTRUCTIONS)

    @server.tool()
    def list_traces(hours: float = 24, limit: int = 20) -> List[dict]:
        """Recent traces with latency, token and cost totals."""
        with _reader() as store:
            return [_trace(row) for row in queries.recent_traces(store, limit=limit, hours=hours)]

    @server.tool()
    def get_trace(trace_id: str) -> dict:
        """One trace and every span in it. An unambiguous id prefix is enough."""
        with _reader() as store:
            row, spans = queries.trace_detail(store, trace_id)
            if row is None:
                raise LookupError(f"no trace matching {trace_id!r}")
            return {"trace": _trace(row), "spans": [_span(span) for span in spans]}

    @server.tool()
    def get_trace_stats(hours: float = 24) -> dict:
        """Volume, latency percentiles, error rate and spend over a window."""
        with _reader() as store:
            return _stats(store, hours)

    @server.tool()
    def search_traces(query: str, limit: int = 20) -> List[dict]:
        """Find traces whose name, input or output contains a substring."""
        with _reader() as store:
            return [_trace(row) for row in queries.search_traces(store, query, limit=limit)]

    @server.tool()
    def list_experiments() -> List[dict]:
        """Every stored experiment with its per-metric means."""
        with _reader() as store:
            return [_experiment(row) for row in queries.experiments(store)]

    @server.tool()
    def get_experiment(name: str) -> dict:
        """One experiment with its per-item scores."""
        with _reader() as store:
            row = queries.experiment(store, name)
            if row is None:
                raise LookupError(f"no experiment named {name!r}")
            items = queries.experiment_items(store, name)
        return {
            "experiment": _experiment(row),
            "items": [
                {
                    "dataset_item_id": item.dataset_item_id,
                    "trace_id": item.trace_id,
                    "output": item.output,
                    "latency_ms": item.latency_ms,
                    "error": item.error,
                    "scores": item.scores,
                }
                for item in items
            ],
        }

    @server.tool()
    def run_faithfulness_audit(trace_id: str, model: str = DEFAULT_MODEL) -> dict:
        """Decompose a RAG trace's answer into claims and check each against its context.

        Costs judge tokens: two LLM calls per audit.
        """
        with _reader() as store:
            result = faithfulness_audit.audit_trace(store, trace_id, model=model)

        saved = _save_audit(result)
        return {
            "audit_id": result.id,
            "trace_id": result.trace_id,
            "score": result.score,
            "saved": saved,
            "query": result.query,
            "answer": result.answer,
            "claims": [
                {
                    "claim": claim.claim,
                    "verdict": claim.verdict,
                    "severity": claim.severity,
                    "rationale": claim.rationale,
                    "evidence": result.evidence_for(claim),
                }
                for claim in sorted(
                    result.claims, key=lambda claim: claim.severity, reverse=True
                )
            ],
        }

    @server.resource("evalforge://stats")
    def stats_resource() -> dict:
        """Current 24-hour statistics for the local trace store."""
        with _reader() as store:
            return _stats(store, 24)

    @server.resource("evalforge://traces/latest")
    def latest_traces_resource() -> List[dict]:
        """The ten most recent traces."""
        with _reader() as store:
            return [_trace(row) for row in queries.recent_traces(store, limit=10)]

    return server


def serve() -> None:
    """Run the server on stdio, the transport assistants launch it with."""
    build().run(transport="stdio")


def _reader() -> Store:
    path = default_db_path()
    if not path.exists():
        raise StoreUnavailable(
            f"no EvalForge database at {path}. Run 'evalforge init' and record a trace first."
        )
    return Store(path, read_only=True)


def _save_audit(result: Any) -> bool:
    """Persist the audit if the write lock is free; report it rather than failing."""
    try:
        with Store() as store:
            faithfulness_audit.save(store, result)
    except DatabaseLocked as error:
        LOGGER.debug("audit not saved, database busy: %s", error)
        return False
    return True


def _stats(store: Store, hours: float) -> Dict[str, Any]:
    summary = queries.trace_summary(store, hours=hours)
    return {
        "window_hours": hours,
        "traces": summary.traces,
        "errors": summary.errors,
        "error_rate": round(summary.error_rate, 4),
        "avg_latency_ms": summary.avg_latency_ms,
        "p50_latency_ms": summary.p50_latency_ms,
        "p95_latency_ms": summary.p95_latency_ms,
        "p99_latency_ms": summary.p99_latency_ms,
        "prompt_tokens": summary.prompt_tokens,
        "completion_tokens": summary.completion_tokens,
        "total_cost_usd": summary.total_cost_usd,
    }


def _trace(row: queries.TraceRow) -> Dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "status": row.status,
        "started_at": _iso(row.start_time),
        "latency_ms": row.latency_ms,
        "spans": row.span_count,
        "tokens": row.tokens,
        "cost_usd": row.cost_usd,
    }


def _span(span: queries.SpanRow) -> Dict[str, Any]:
    return {
        "id": span.id,
        "parent_span_id": span.parent_span_id,
        "name": span.name,
        "type": span.type,
        "status": span.status,
        "latency_ms": span.latency_ms,
        "model": span.model,
        "prompt_tokens": span.prompt_tokens,
        "completion_tokens": span.completion_tokens,
        "cost_usd": span.cost_usd,
        "input": span.input,
        "output": span.output,
        "error": span.error,
    }


def _experiment(row: queries.ExperimentRow) -> Dict[str, Any]:
    return {
        "name": row.name,
        "dataset": row.dataset_name,
        "items": row.items,
        "errors": row.errors,
        "created_at": _iso(row.created_at),
        "means": {metric: round(row.means[metric], 4) for metric in row.metrics},
        "higher_is_better": row.polarity,
    }


def _iso(moment: Optional[Any]) -> Optional[str]:
    return moment.isoformat() if moment is not None else None
