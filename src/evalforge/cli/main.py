"""The evalforge command line."""

import logging
import time
from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from .. import __version__
from ..core.spool import default_home, default_spool_dir
from ..storage.duckdb_store import Store, default_db_path
from ..storage.ingest import ingest_once

console = Console()


@click.group()
@click.version_option(__version__, prog_name="evalforge")
@click.option("--verbose", is_flag=True, help="Log at DEBUG level.")
def cli(verbose: bool) -> None:
    """Trace, evaluate and inspect LLM applications."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
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
@click.option(
    "--spool", type=click.Path(path_type=Path), help="Spool directory to read from."
)
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
    db_path = default_db_path()
    spool_dir = default_spool_dir()
    pending = len(list(spool_dir.glob("*.ndjson"))) if spool_dir.is_dir() else 0

    if not db_path.exists():
        console.print("[yellow]no database yet - run 'evalforge init'[/yellow]")
    else:
        with Store(db_path, read_only=True) as store:
            console.print(
                f"traces [green]{store.count('traces')}[/green]  "
                f"spans [green]{store.count('spans')}[/green]  "
                f"scores [green]{store.count('feedback_scores')}[/green]"
            )
    console.print(f"spool files waiting: [cyan]{pending}[/cyan]")
