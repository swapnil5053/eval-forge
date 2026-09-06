import datetime

import pytest
from click.testing import CliRunner

from evalforge.cli.main import cli
from evalforge.storage.duckdb_store import Store

_WHEN = datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture
def runs(tmp_path, monkeypatch):
    """Two experiments over one item: a baseline and a run to judge against it."""
    monkeypatch.setenv("EVALFORGE_HOME", str(tmp_path / "forge"))
    with Store(tmp_path / "forge" / "evalforge.db") as store:
        store.upsert("datasets", [{"id": "d1", "name": "set", "created_at": _WHEN}])
        store.upsert(
            "dataset_items",
            [{"id": "i1", "dataset_id": "d1", "input": {"q": "?"}, "created_at": _WHEN}],
        )
        for name, faithful, hallucinated in (("base", 0.80, 0.10), ("candidate", 0.60, 0.30)):
            store.upsert(
                "experiments",
                [{"id": name, "name": name, "dataset_id": "d1", "created_at": _WHEN}],
            )
            store.upsert(
                "experiment_results",
                [
                    {
                        "id": f"r-{name}",
                        "experiment_id": name,
                        "dataset_item_id": "i1",
                        "scores": {
                            "faithfulness": {"value": faithful, "higher_is_better": True},
                            "hallucination": {"value": hallucinated, "higher_is_better": False},
                        },
                        "created_at": _WHEN,
                    }
                ],
            )


def gate(*args):
    return CliRunner().invoke(cli, ["eval", "gate", *args])


def test_a_regression_exits_non_zero_so_ci_can_stop_a_merge(runs):
    result = gate("candidate", "--baseline", "base")
    assert result.exit_code == 1
    assert "faithfulness" in result.output


def test_a_lower_hallucination_score_is_an_improvement_not_a_drop(runs):
    """Polarity decides the direction. Hallucination rose here, so it must fail."""
    result = gate("candidate", "--baseline", "base", "--metric", "hallucination")
    assert result.exit_code == 1
    assert "-0.200" in result.output


def test_the_same_comparison_the_other_way_round_passes(runs):
    result = gate("base", "--baseline", "candidate")
    assert result.exit_code == 0
    assert "no metric moved" in result.output


def test_a_wide_enough_threshold_tolerates_the_drop(runs):
    assert gate("candidate", "--baseline", "base", "--max-drop", "0.5").exit_code == 0


def test_gating_on_one_metric_ignores_the_others(runs):
    result = gate("candidate", "--baseline", "base", "--metric", "faithfulness")
    assert "hallucination" not in result.output


def test_an_unknown_experiment_says_how_to_find_the_real_ones(runs):
    result = gate("ghost", "--baseline", "base")
    assert result.exit_code != 0
    assert "eval list" in result.output


def test_a_negative_threshold_is_refused(runs):
    assert gate("candidate", "--baseline", "base", "--max-drop", "-0.1").exit_code != 0
