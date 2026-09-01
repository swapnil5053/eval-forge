"""Shared bits of the command line: the console, formatting, opening the database."""

import json
from typing import Any, Optional

import click
from rich.console import Console

from ..storage.duckdb_store import Store, default_db_path

console = Console()

STATUS_COLOURS = {"ok": "green", "error": "red"}
TYPE_COLOURS = {"llm": "magenta", "retrieval": "cyan", "tool": "yellow"}


def read_only_store() -> Store:
    """Open the database for reading, or explain why we cannot."""
    path = default_db_path()
    if not path.exists():
        raise click.ClickException("no database yet - run 'evalforge init'")
    return Store(path, read_only=True)


def status(value: str) -> str:
    colour = STATUS_COLOURS.get(value, "white")
    return f"[{colour}]{value}[/{colour}]"


def span_type(value: str) -> str:
    colour = TYPE_COLOURS.get(value)
    return f"[{colour}]{value}[/{colour}]" if colour else f"[dim]{value}[/dim]"


def milliseconds(latency: Optional[float]) -> str:
    if latency is None:
        return "-"
    return f"{latency:.0f}ms" if latency < 1000 else f"{latency / 1000:.2f}s"


def cost(usd: Optional[float]) -> str:
    if not usd:
        return "-"
    return f"${usd:.6f}" if usd < 0.01 else f"${usd:.4f}"


def brief(value: Any, limit: int = 160) -> str:
    if value is None:
        return "[dim]none[/dim]"
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[:limit]}..."
