import sys

import pytest

from evalforge.eval import judge


def test_parses_a_bare_object():
    assert judge.parse_json('{"score": 0.5}') == {"score": 0.5}


def test_parses_a_fenced_object():
    content = 'Here you go:\n```json\n{"score": 0.25, "reason": "thin"}\n```'
    assert judge.parse_json(content)["score"] == 0.25


def test_parses_an_object_buried_in_prose():
    assert judge.parse_json('Sure. {"score": 1.0} Hope that helps.') == {"score": 1.0}


def test_rejects_a_response_with_no_object():
    with pytest.raises(judge.JudgeError, match="did not return a JSON object"):
        judge.parse_json("I would rather not.")


def test_rejects_a_json_array():
    with pytest.raises(judge.JudgeError):
        judge.parse_json("[1, 2, 3]")


def test_unit_score_range_is_enforced():
    assert judge.unit_score({"score": "0.5"}) == 0.5
    with pytest.raises(judge.JudgeError, match="between 0.0 and 1.0"):
        judge.unit_score({"score": 1.5})
    with pytest.raises(judge.JudgeError, match="no numeric"):
        judge.unit_score({"reason": "none given"})


def test_reason_accepts_a_list():
    assert judge.as_reason(["first", "second"]) == "first second"
    assert judge.as_reason(None) == ""


def test_required_keys_are_checked(judge_stub):
    judge_stub.default = {"reason": "no score here"}
    with pytest.raises(judge.JudgeError, match="missing 'score'"):
        judge.judge_json("system", "user", required=["score"])


def test_without_litellm_the_error_says_what_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)
    with pytest.raises(judge.JudgeError, match="pip install evalforge\\[eval\\]"):
        judge.complete("system", "user")
