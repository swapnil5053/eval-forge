"""The 'evalforge serve' command.

Reflex wants a project directory of its own - an rxconfig.py and a module it can
import. Rather than making the repository look like a Reflex app, serve scaffolds
that directory under the EvalForge home and points it back at this package.
"""

import logging
import shutil
import subprocess
import threading
import webbrowser
from pathlib import Path

import click

from ..core.spool import default_home
from ..storage.duckdb_store import Store
from ..storage.ingest import ingest_once
from .support import console

LOGGER = logging.getLogger(__name__)

APP_NAME = "evalforge_panel"
BROWSER_DELAY_SECONDS = 4.0

_CONFIG = f'''import reflex as rx

config = rx.Config(
    app_name="{APP_NAME}",
    telemetry_enabled=False,
    show_built_with_reflex=False,
)
'''

_MODULE = """from evalforge.dashboard.app import app

__all__ = ["app"]
"""


@click.group("mcp")
def mcp_group() -> None:
    """Expose the trace store over the Model Context Protocol."""


@mcp_group.command("serve")
def mcp_serve() -> None:
    """Run the MCP server on stdio, for Claude, Cursor or any MCP client."""
    from ..mcp.server import StoreUnavailable, serve as run_server

    try:
        run_server()
    except (ImportError, StoreUnavailable) as error:
        raise click.ClickException(str(error)) from error


@mcp_group.command("install")
def mcp_install() -> None:
    """Print the client config block that registers this server."""
    console.print_json(
        data={
            "mcpServers": {
                "evalforge": {"command": "evalforge", "args": ["mcp", "serve"]}
            }
        }
    )


@click.command()
@click.option("--port", default=8000, show_default=True, help="Port to serve on.")
@click.option("--no-browser", is_flag=True, help="Do not open a browser window.")
@click.option("--no-ingest", is_flag=True, help="Skip the ingestion pass on startup.")
def serve(port: int, no_browser: bool, no_ingest: bool) -> None:
    """Ingest pending traces, then run the dashboard."""
    if shutil.which("reflex") is None:
        raise click.ClickException(
            "the dashboard needs reflex. Install it with 'pip install evalforge[dashboard]'."
        )

    if not no_ingest:
        with Store() as store:
            result = ingest_once(store)
        if result.files:
            console.print(f"ingested [green]{result.records}[/green] pending record(s)")

    project = _scaffold()
    url = f"http://localhost:{port}"
    console.print(f"EvalForge dashboard running at [cyan]{url}[/cyan]")
    console.print("[dim]Press Ctrl+C to stop[/dim]")

    if not no_browser:
        threading.Timer(BROWSER_DELAY_SECONDS, webbrowser.open, args=[url]).start()

    command = ["reflex", "run", "--single-port", "--frontend-port", str(port)]
    try:
        subprocess.run(command, cwd=project, check=True)
    except KeyboardInterrupt:
        console.print("\n[dim]stopped[/dim]")
    except subprocess.CalledProcessError as error:
        raise click.ClickException(f"reflex exited with status {error.returncode}") from error


def _scaffold() -> Path:
    """Create (or refresh) the Reflex project that wraps the dashboard package."""
    project = default_home() / "panel"
    package = project / APP_NAME
    package.mkdir(parents=True, exist_ok=True)

    _write(project / "rxconfig.py", _CONFIG)
    _write(package / "__init__.py", _MODULE)
    _write(package / f"{APP_NAME}.py", _MODULE)
    return project


def _write(path: Path, content: str) -> None:
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8")
        LOGGER.debug("wrote %s", path)
