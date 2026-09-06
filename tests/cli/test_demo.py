import pytest
from click.testing import CliRunner

from evalforge import demo
from evalforge.cli.main import cli
from evalforge.storage import queries
from evalforge.storage.duckdb_store import Store


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALFORGE_HOME", str(tmp_path / "forge"))
    return tmp_path / "forge"


@pytest.fixture
def seeded(home):
    result = CliRunner().invoke(cli, ["demo", "--no-serve"])
    assert result.exit_code == 0, result.output
    return home / "evalforge.db"


def test_demo_fills_every_page_the_panel_has(seeded):
    with Store(seeded, read_only=True) as store:
        assert queries.trace_summary(store, hours=24).traces > 0
        assert queries.recent_errors(store)
        assert queries.token_usage(store, hours=24)
        assert len(queries.experiments(store)) == 3
        assert queries.datasets(store)
        assert store.count("faithfulness_audits") == 3


def test_the_same_seed_gives_the_same_database(tmp_path):
    def fingerprint(name):
        with Store(tmp_path / name) as store:
            demo.seed(store, rng_seed=demo.SEED)
            return store.db.execute(
                "SELECT sum(prompt_tokens), sum(completion_tokens), count(*) FROM spans"
            ).fetchone()

    assert fingerprint("one.db") == fingerprint("two.db")


def test_scores_land_in_the_shape_the_experiment_runner_writes(seeded):
    """A list here would summarise as an experiment with no metrics at all."""
    with Store(seeded, read_only=True) as store:
        for run in queries.experiments(store):
            assert set(run.means) == {"answer_relevance", "faithfulness"}
            assert run.polarity == {"answer_relevance": True, "faithfulness": True}


def test_generation_carries_the_spend_not_the_classifier(seeded):
    with Store(seeded, read_only=True) as store:
        rows = queries.cost_breakdown(store, hours=24)
    assert rows[0].key == "generate"


def test_a_second_demo_refuses_rather_than_doubling_the_data(seeded):
    result = CliRunner().invoke(cli, ["demo", "--no-serve"])
    assert result.exit_code != 0
    assert "--replace" in result.output


def test_replace_reseeds_instead_of_appending(seeded):
    with Store(seeded, read_only=True) as store:
        before = store.count("traces")

    result = CliRunner().invoke(cli, ["demo", "--no-serve", "--replace"])
    assert result.exit_code == 0, result.output

    with Store(seeded, read_only=True) as store:
        assert store.count("traces") == before
        assert store.count("audit_claims") == 11


def test_demo_needs_no_network_or_api_key(seeded, monkeypatch):
    """The seeder must not reach for litellm or a key - that is the whole point."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    source = (demo.__file__)
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    assert "litellm" not in text
    assert "requests" not in text
