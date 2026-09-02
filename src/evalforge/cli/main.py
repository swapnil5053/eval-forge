"""The evalforge command line."""

import logging
import time
from pathlib import Path
from typing import List, Optional

import click
from rich.table import Table
from rich.tree import Tree

from .. import __version__
from ..core.spool import default_home, default_spool_dir
from ..storage import queries
from ..storage.duckdb_store import Store
from ..storage.ingest import ingest_once
from .commands_eval import commands as eval_commands
from .serve import serve
from .support import brief as _brief
from .support import console, cost as _cost, milliseconds as _ms
from .support import read_only_store as _read_only, span_type as _type, status as _status


@click.group()
@click.version_option(__version__, prog_name="evalforge")
@click.option("--verbose", is_flag=True, help="Log at DEBUG level.")
def cli(verbose: bool) -> None:
    """Trace, evaluate and inspect LLM applications."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


@cli.command()
@click.option("--db", type=click.Path(path_type=Path), help="Database file to create.")
def init(db: Optional[Path]) -> None:
    """Create the EvalForge home directory and database."""
    spool_dir = default_spool_dir()
    spool_dir.mkdir(parents=True, exist_ok=True)
    with Store(db) as store:
        console.print(f"database  [cyan]{store.path}[/cyan]")
    console.print(f"spool     [cyan]{spool_dir}[/cyan]")
    console.print(f"home      [cyan]{default_home()}[/cyan]")


@cli.command()
@click.option("--db", type=click.Path(path_type=Path), help="Database file to write to.")
@click.option("--spool", type=click.Path(path_type=Path), help="Spool directory to read.")
@click.option("--watch", is_flag=True, help="Keep ingesting until interrupted.")
@click.option("--interval", default=2.0, show_default=True, help="Seconds between passes.")
def ingest(db: Optional[Path], spool: Optional[Path], watch: bool, interval: float) -> None:
    """Load spooled traces into DuckDB."""
    with Store(db) as store:
        while True:
            result = ingest_once(store, spool)
            if result.files:
                console.print(
                    f"ingested [green]{result.records}[/green] records "
                    f"from {result.files} file(s)"
                )
            if result.skipped_lines:
                console.print(f"[yellow]skipped {result.skipped_lines} line(s)[/yellow]")
            if not watch:
                return
            time.sleep(interval)


@cli.command()
def status() -> None:
    """Show what is in the database and what is waiting in the spool."""
    spool_dir = default_spool_dir()
    pending = len(list(spool_dir.glob("*.ndjson"))) if spool_dir.is_dir() else 0
    with _read_only() as store:
        console.print(
            f"traces [green]{store.count('traces')}[/green]  "
            f"spans [green]{store.count('spans')}[/green]  "
            f"scores [green]{store.count('feedback_scores')}[/green]"
        )
    console.print(f"spool files waiting: [cyan]{pending}[/cyan]")


@cli.group()
def trace() -> None:
    """Inspect recorded traces."""


@trace.command("list")
@click.option("--limit", default=20, show_default=True, help="Rows to show.")
@click.option("--hours", type=float, help="Only traces started in the last N hours.")
def trace_list(limit: int, hours: Optional[float]) -> None:
    """Show the most recent traces."""
    with _read_only() as store:
        _print_traces(queries.recent_traces(store, limit=limit, hours=hours), "Recent traces")


@trace.command("search")
@click.argument("query")
@click.option("--limit", default=20, show_default=True, help="Rows to show.")
def trace_search(query: str, limit: int) -> None:
    """Find traces whose name, input or output contains QUERY."""
    with _read_only() as store:
        _print_traces(queries.search_traces(store, query, limit=limit), f"Traces matching {query!r}")


@trace.command("slow")
@click.option("--threshold-ms", default=1000.0, show_default=True, help="Minimum latency.")
@click.option("--limit", default=20, show_default=True, help="Rows to show.")
def trace_slow(threshold_ms: float, limit: int) -> None:
    """Show traces slower than a threshold."""
    with _read_only() as store:
        rows = queries.slow_traces(store, threshold_ms, limit=limit)
        _print_traces(rows, f"Traces slower than {threshold_ms:.0f} ms")


@trace.command("stats")
@click.option("--hours", default=24.0, show_default=True, help="Window to summarise.")
def trace_stats(hours: float) -> None:
    """Summarise volume, latency, errors and spend."""
    with _read_only() as store:
        summary = queries.trace_summary(store, hours=hours)
        if not summary.traces:
            console.print(f"[yellow]no traces in the last {hours:g}h[/yellow]")
            return

        table = Table(title=f"Last {hours:g}h", box=None, pad_edge=False)
        table.add_column("metric", style="dim")
        table.add_column("value", justify="right")
        error_style = "red" if summary.errors else "green"
        for label, value in [
            ("traces", str(summary.traces)),
            ("errors", f"[{error_style}]{summary.errors} ({summary.error_rate:.0%})[/{error_style}]"),
            ("latency avg", _ms(summary.avg_latency_ms)),
            ("latency p50", _ms(summary.p50_latency_ms)),
            ("latency p95", _ms(summary.p95_latency_ms)),
            ("latency p99", _ms(summary.p99_latency_ms)),
            ("tokens in/out", f"{summary.prompt_tokens}/{summary.completion_tokens}"),
            ("cost", _cost(summary.total_cost_usd)),
        ]:
            table.add_row(label, value)
        console.print(table)

        _print_groups(queries.token_usage(store, hours=hours), "Tokens by model", "model")
        _print_groups(
            queries.cost_breakdown(store, hours=hours), "Cost by function", "function"
        )


@trace.command("show")
@click.argument("trace_id")
@click.option("--full", is_flag=True, help="Print span inputs and outputs.")
def trace_show(trace_id: str, full: bool) -> None:
    """Show one trace as a span tree. TRACE_ID may be an id prefix."""
    with _read_only() as store:
        try:
            row, spans = queries.trace_detail(store, trace_id)
        except ValueError as error:
            raise click.ClickException(str(error)) from error

    if row is None:
        raise click.ClickException(f"no trace matching {trace_id!r}")

    header = (
        f"[bold]{row.name}[/bold] {_status(row.status)}  {_ms(row.latency_ms)}  "
        f"{row.span_count} spans  {_cost(row.cost_usd)}\n[dim]{row.id}[/dim]"
    )
    tree = Tree(header)
    children: dict = {}
    for span in spans:
        children.setdefault(span.parent_span_id, []).append(span)
    _grow(tree, children, None, full)
    console.print(tree)


def _grow(node: Tree, children: dict, parent_id: Optional[str], full: bool) -> None:
    for span in children.get(parent_id, []):
        label = (
            f"{_type(span.type)} [bold]{span.name}[/bold] {_status(span.status)} "
            f"[dim]{_ms(span.latency_ms)}[/dim]"
        )
        if span.prompt_tokens or span.completion_tokens:
            label += f" [dim]{span.prompt_tokens or 0}/{span.completion_tokens or 0} tok[/dim]"
        if span.cost_usd:
            label += f" [dim]{_cost(span.cost_usd)}[/dim]"
        branch = node.add(label)
        if span.error:
            branch.add(f"[red]{span.error.strip().splitlines()[-1]}[/red]")
        if full:
            branch.add(f"[dim]in [/dim] {_brief(span.input)}")
            branch.add(f"[dim]out[/dim] {_brief(span.output)}")
        _grow(branch, children, span.id, full)


def _print_traces(rows: List[queries.TraceRow], title: str) -> None:
    if not rows:
        console.print("[yellow]no matching traces[/yellow]")
        return

    table = Table(title=title, header_style="dim")
    table.add_column("id", style="dim", no_wrap=True)
    table.add_column("name")
    table.add_column("status")
    table.add_column("latency", justify="right")
    table.add_column("spans", justify="right")
    table.add_column("tokens", justify="right")
    table.add_column("cost", justify="right")
    table.add_column("started", style="dim")
    for row in rows:
        table.add_row(
            row.id[:8],
            row.name,
            _status(row.status),
            _ms(row.latency_ms),
            str(row.span_count),
            str(row.tokens or ""),
            _cost(row.cost_usd),
            row.start_time.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        )
    console.print(table)


def _print_groups(rows: List[queries.GroupRow], title: str, key_header: str) -> None:
    if not rows:
        return
    table = Table(title=title, box=None, header_style="dim", pad_edge=False)
    table.add_column(key_header)
    table.add_column("spans", justify="right")
    table.add_column("tokens", justify="right")
    table.add_column("cost", justify="right")
    for row in rows:
        table.add_row(row.key, str(row.spans), str(row.tokens or ""), _cost(row.cost_usd))
    console.print(table)


for group in eval_commands():
    cli.add_command(group)

cli.add_command(serve)
