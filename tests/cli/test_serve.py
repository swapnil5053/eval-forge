import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from evalforge.cli import serve as serve_module
from evalforge.cli.main import cli


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALFORGE_HOME", str(tmp_path / "forge"))
    return tmp_path / "forge"


@pytest.fixture
def launched(monkeypatch):
    """Capture the reflex invocation instead of running it."""
    calls = {}

    def fake_run(command, cwd=None, check=False):
        calls["command"] = command
        calls["cwd"] = Path(cwd)
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(serve_module, "dashboard_installed", lambda: True)
    monkeypatch.setattr(serve_module.subprocess, "run", fake_run)
    monkeypatch.setattr(serve_module.webbrowser, "open", lambda url: None)
    monkeypatch.setattr(serve_module.threading, "Timer", lambda *a, **k: type(
        "Timer", (), {"start": lambda self: None}
    )())
    return calls


def test_single_port_requires_production_mode(home, launched):
    """Reflex rejects --single-port outside prod, which broke serve entirely."""
    result = CliRunner().invoke(cli, ["serve", "--no-browser"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    command = launched["command"]
    assert command[:4] == [sys.executable, "-m", "reflex", "run"]
    assert "--single-port" in command
    assert command[command.index("--env") + 1] == "prod"


def test_reflex_runs_under_this_interpreter_not_whichever_is_on_path(home, launched):
    """A reflex outside this virtualenv cannot import evalforge to find the app."""
    CliRunner().invoke(cli, ["serve", "--no-browser"], catch_exceptions=False)

    assert launched["command"][0] == sys.executable


def test_the_port_reaches_reflex_and_the_message(home, launched):
    result = CliRunner().invoke(cli, ["serve", "--port", "8123", "--no-browser"],
                                catch_exceptions=False)

    command = launched["command"]
    assert command[command.index("--frontend-port") + 1] == "8123"
    assert "http://localhost:8123" in result.output
    assert "Ctrl+C" in result.output


def test_the_app_is_defined_once(home, launched):
    """Reflex imports the package and its module; defining app in both double-registers."""
    CliRunner().invoke(cli, ["serve", "--no-browser"], catch_exceptions=False)

    package = launched["cwd"] / serve_module.APP_NAME
    assert (package / "__init__.py").read_text(encoding="utf-8") == ""
    assert "from evalforge.dashboard.app import app" in (
        package / f"{serve_module.APP_NAME}.py"
    ).read_text(encoding="utf-8")
    assert (launched["cwd"] / "rxconfig.py").exists()


def test_serve_ingests_before_starting(home, launched):
    CliRunner().invoke(cli, ["serve", "--no-browser"], catch_exceptions=False)
    assert (home / "evalforge.db").exists()


def test_no_ingest_skips_the_pass(home, launched, monkeypatch):
    called = []
    monkeypatch.setattr(serve_module, "ingest_once", lambda store: called.append(1))

    CliRunner().invoke(cli, ["serve", "--no-browser", "--no-ingest"], catch_exceptions=False)

    assert called == []


def test_a_missing_reflex_says_what_to_install(home, monkeypatch):
    monkeypatch.setattr(serve_module, "dashboard_installed", lambda: False)

    result = CliRunner().invoke(cli, ["serve"])

    assert result.exit_code != 0
    assert "evalforge[dashboard]" in result.output
