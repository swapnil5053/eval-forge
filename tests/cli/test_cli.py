import pytest
from click.testing import CliRunner

from evalforge import trace
from evalforge.cli.main import cli
from evalforge.core import spool
from evalforge.storage.duckdb_store import Store
from evalforge.storage.queries import recent_traces


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALFORGE_HOME", str(tmp_path / "forge"))
    return tmp_path / "forge"


@pytest.fixture
def runner(monkeypatch):
    # Rich truncates columns to the terminal width, and the default in a captured
    # run is 80. Give it room so assertions see whole values.
    monkeypatch.setenv("COLUMNS", "200")
    return CliRunner()


def invoke(runner, *args):
    result = runner.invoke(cli, list(args), catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return result.output


def record_traces(home):
    writer = spool.SpoolWriter(home / "spool")
    spool.set_writer(writer)
    try:

        @trace(name="generate", type="llm")
        def generate(question):
            return {
                "model": "gpt-4o-mini",
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            }

        @trace(name="rag-pipeline")
        def answer(question):
            return generate(question)

        @trace(name="broken")
        def broken():
            raise RuntimeError("vector store unreachable")

        answer("capital of France")
        with pytest.raises(RuntimeError):
            broken()
    finally:
        writer.close()
        spool.set_writer(None)


def test_init_creates_home(runner, home):
    output = invoke(runner, "init")

    assert (home / "evalforge.db").exists()
    assert (home / "spool").is_dir()
    assert "database" in output


def test_commands_before_init_explain_themselves(runner, home):
    result = runner.invoke(cli, ["trace", "list"])
    assert result.exit_code != 0
    assert "evalforge init" in result.output


def test_full_cycle(runner, home):
    invoke(runner, "init")
    record_traces(home)

    assert "ingested" in invoke(runner, "ingest")

    listed = invoke(runner, "trace", "list")
    assert "rag-pipeline" in listed
    assert "broken" in listed
    assert "error" in listed

    stats = invoke(runner, "trace", "stats")
    assert "traces" in stats
    assert "gpt-4o-mini" in stats

    assert "rag-pipeline" in invoke(runner, "trace", "search", "capital")
    assert "no matching traces" in invoke(runner, "trace", "search", "zzz")

    assert "spool files waiting: 0" in invoke(runner, "status")


def test_show_renders_the_span_tree(runner, home):
    invoke(runner, "init")
    record_traces(home)
    invoke(runner, "ingest")

    with Store(home / "evalforge.db", read_only=True) as store:
        trace_id = next(
            row.id for row in recent_traces(store) if row.name == "rag-pipeline"
        )

    shown = invoke(runner, "trace", "show", trace_id, "--full")
    assert "rag-pipeline" in shown
    assert "generate" in shown
    assert "capital of France" in shown


def test_show_reports_an_unknown_id(runner, home):
    invoke(runner, "init")
    result = runner.invoke(cli, ["trace", "show", "deadbeef"])
    assert result.exit_code != 0
    assert "no trace matching" in result.output


def test_stats_on_an_empty_database(runner, home):
    invoke(runner, "init")
    assert "no traces" in invoke(runner, "trace", "stats")
