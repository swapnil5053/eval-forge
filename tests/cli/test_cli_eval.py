import pytest
from click.testing import CliRunner

from evalforge import trace
from evalforge.cli.main import cli
from evalforge.core import spool
from evalforge.eval import dataset
from evalforge.storage.duckdb_store import Store

CONTEXT = ["Paris has been the capital of France since 987."]

TASK_MODULE = '''
from evalforge import trace


@trace(name="retrieve", type="retrieval")
def retrieve(question):
    return ["Paris has been the capital of France since 987."]


@trace(name="generate", type="llm")
def generate(question, context):
    return {"choices": [{"message": {"content": "Paris."}}]}


@trace(name="rag")
def answer(item):
    question = item["question"]
    return generate(question, retrieve(question))["choices"][0]["message"]["content"]
'''


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALFORGE_HOME", str(tmp_path / "forge"))
    monkeypatch.setenv("COLUMNS", "200")
    return tmp_path / "forge"


@pytest.fixture
def runner():
    return CliRunner()


def invoke(runner, *args):
    result = runner.invoke(cli, list(args), catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return result.output


def test_eval_run_from_a_yaml_file(runner, home, tmp_path, judge_stub, monkeypatch):
    invoke(runner, "init")

    (tmp_path / "pipeline_under_test.py").write_text(TASK_MODULE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    with Store(home / "evalforge.db") as store:
        dataset.create(
            store,
            "capitals",
            [{"input": {"question": "capital of France?", "context": CONTEXT},
              "expected_output": "Paris"}],
        )

    config = tmp_path / "experiment.yaml"
    config.write_text(
        "name: rag-v1\n"
        "dataset: capitals\n"
        "task: pipeline_under_test:answer\n"
        "metrics: [faithfulness, hallucination]\n"
        "workers: 2\n",
        encoding="utf-8",
    )

    output = invoke(runner, "eval", "run", str(config))
    assert "rag-v1" in output
    assert "faithfulness" in output
    assert "higher is better" in output
    assert "lower is better" in output

    assert "rag-v1" in invoke(runner, "eval", "list")
    assert "capitals" in invoke(runner, "eval", "datasets")

    shown = invoke(runner, "eval", "show", "rag-v1")
    assert "faithfulness" in shown
    assert "Paris" in shown


def test_eval_run_rejects_an_incomplete_config(runner, home, tmp_path):
    invoke(runner, "init")
    config = tmp_path / "experiment.yaml"
    config.write_text("name: nope\n", encoding="utf-8")

    result = runner.invoke(cli, ["eval", "run", str(config)])
    assert result.exit_code != 0
    assert "missing required key 'dataset'" in result.output


def test_eval_run_rejects_an_unknown_metric(runner, home, tmp_path):
    invoke(runner, "init")
    config = tmp_path / "experiment.yaml"
    config.write_text(
        "dataset: capitals\ntask: pipeline_under_test:answer\nmetrics: [vibes]\n",
        encoding="utf-8",
    )

    result = runner.invoke(cli, ["eval", "run", str(config)])
    assert result.exit_code != 0
    assert "unknown metric" in result.output


def test_eval_run_rejects_a_task_that_is_not_importable(runner, home, tmp_path):
    invoke(runner, "init")
    config = tmp_path / "experiment.yaml"
    config.write_text("dataset: capitals\ntask: not_a_module:answer\n", encoding="utf-8")

    result = runner.invoke(cli, ["eval", "run", str(config)])
    assert result.exit_code != 0
    assert "could not import" in result.output


def test_eval_show_reports_an_unknown_experiment(runner, home):
    invoke(runner, "init")
    result = runner.invoke(cli, ["eval", "show", "absent"])
    assert result.exit_code != 0
    assert "no experiment named" in result.output


def test_audit_run_list_and_show(runner, home, judge_stub):
    invoke(runner, "init")
    _record_rag_trace(home)
    invoke(runner, "ingest")

    judge_stub.script = [
        ("You split an answer", {"claims": ["Paris is the capital.", "It has 9 bridges."]}),
        (
            "You check each claim",
            {
                "verdicts": [
                    {"index": 0, "verdict": "SUPPORTED", "evidence": [0], "rationale": "passage 0"},
                    {"index": 1, "verdict": "UNSUPPORTED", "evidence": [], "rationale": "silent"},
                ]
            },
        ),
    ]

    with Store(home / "evalforge.db", read_only=True) as store:
        trace_id = store.db.execute("SELECT id FROM traces").fetchone()[0]

    output = invoke(runner, "audit", "run", trace_id[:8])
    assert "faithfulness 0.50" in output
    assert "UNSUPPORTED" in output
    assert "SUPPORTED" in output
    assert "evidence:" in output

    listed = invoke(runner, "audit", "list")
    assert trace_id[:8] in listed

    with Store(home / "evalforge.db", read_only=True) as store:
        audit_id = store.db.execute("SELECT id FROM faithfulness_audits").fetchone()[0]
    assert "It has 9 bridges." in invoke(runner, "audit", "show", audit_id[:8])


def test_audit_run_explains_a_trace_that_is_not_rag(runner, home, judge_stub):
    invoke(runner, "init")

    writer = spool.SpoolWriter(home / "spool")
    spool.set_writer(writer)
    try:

        @trace(name="plain")
        def plain():
            return "no retrieval here"

        plain()
    finally:
        writer.close()
        spool.set_writer(None)

    invoke(runner, "ingest")
    with Store(home / "evalforge.db", read_only=True) as store:
        trace_id = store.db.execute("SELECT id FROM traces").fetchone()[0]

    result = runner.invoke(cli, ["audit", "run", trace_id[:8]])
    assert result.exit_code != 0
    assert "cannot be audited as RAG" in result.output


def test_audit_list_when_there_are_none(runner, home):
    invoke(runner, "init")
    assert "no audits yet" in invoke(runner, "audit", "list")


def _record_rag_trace(home):
    writer = spool.SpoolWriter(home / "spool")
    spool.set_writer(writer)
    try:

        @trace(name="retrieve", type="retrieval")
        def retrieve(question):
            return CONTEXT

        @trace(name="generate", type="llm")
        def generate(question, context):
            return {"choices": [{"message": {"content": "Paris. It has 9 bridges."}}]}

        @trace(name="rag")
        def answer(question):
            return generate(question, retrieve(question))

        answer("capital of France?")
    finally:
        writer.close()
        spool.set_writer(None)
