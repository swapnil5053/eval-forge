import pytest

from evalforge.eval import judge, metrics


def test_every_metric_is_registered():
    assert set(metrics.METRICS) == {
        "hallucination",
        "faithfulness",
        "answer_relevance",
        "context_precision",
        "context_recall",
        "toxicity",
        "coherence",
        "conciseness",
    }


def test_lookup_by_name():
    assert metrics.get("faithfulness") is metrics.faithfulness
    with pytest.raises(ValueError, match="unknown metric"):
        metrics.get("vibes")


def test_a_metric_returns_a_score(judge_stub):
    judge_stub.default = {"score": 0.9, "reason": "grounded in passage 0"}

    score = metrics.faithfulness(
        input="What is the capital of France?",
        output="Paris.",
        context=["Paris is the capital of France."],
    )

    assert score.metric_name == "faithfulness"
    assert score.value == 0.9
    assert score.reason == "grounded in passage 0"
    assert score.higher_is_better is True
    assert score.failed is False


def test_the_context_reaches_the_judge(judge_stub):
    metrics.faithfulness(
        input="capital?", output="Paris.", context=["Paris is the capital.", "Berlin is not."]
    )

    user = judge_stub.calls[0]["user"]
    assert "[0] Paris is the capital." in user
    assert "[1] Berlin is not." in user
    assert "OUTPUT:\nParis." in user


def test_hallucination_and_toxicity_are_lower_is_better(judge_stub):
    judge_stub.default = {"score": 0.8, "reason": "invented a date"}

    hallucination = metrics.hallucination(input="q", output="a", context=["c"])
    toxic = metrics.toxicity(output="a")

    assert hallucination.higher_is_better is False
    assert hallucination.failed is True
    assert toxic.higher_is_better is False


def test_a_good_score_on_an_inverted_metric_does_not_count_as_failed(judge_stub):
    judge_stub.default = {"score": 0.1, "reason": "faithful"}
    assert metrics.hallucination(input="q", output="a", context=["c"]).failed is False


def test_reason_lists_are_joined(judge_stub):
    judge_stub.default = {"score": 0.3, "reason": ["first problem", "second problem"]}
    assert metrics.answer_relevance(input="q", output="a").reason == (
        "first problem second problem"
    )


def test_the_model_is_passed_through_and_recorded(judge_stub):
    score = metrics.coherence(output="a paragraph", model="ollama/llama3")

    assert judge_stub.calls[0]["model"] == "ollama/llama3"
    assert score.metadata == {"model": "ollama/llama3"}


def test_an_out_of_range_score_is_rejected(judge_stub):
    judge_stub.default = {"score": 7, "reason": "out of ten, apparently"}
    with pytest.raises(judge.JudgeError, match="between 0.0 and 1.0"):
        metrics.conciseness(output="a")


def test_empty_sections_are_left_out(judge_stub):
    metrics.toxicity(output="hello")
    assert "INPUT:" not in judge_stub.calls[0]["user"]
