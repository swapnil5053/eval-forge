import sys

import pytest

from evalforge.eval import attribution
from evalforge.storage.duckdb_store import Store

TEXT = "the capital of France is Paris"


def keyword_score(text):
    """A stand-in scorer: 'France' carries the score, 'Paris' carries half."""
    return 1.0 * ("France" in text) + 0.5 * ("Paris" in text)


def test_tokenize_splits_on_whitespace():
    assert attribution.tokenize(" two  words ") == ["two", "words"]


def test_occlusion_finds_the_tokens_that_carry_the_score():
    result = attribution.attribute(TEXT, keyword_score, method="occlusion")

    assert result.method == "occlusion"
    assert result.baseline == 1.5
    assert dict(zip(result.tokens, result.scores))["France"] == 1.0
    assert dict(zip(result.tokens, result.scores))["Paris"] == 0.5
    assert dict(zip(result.tokens, result.scores))["the"] == 0.0


def test_top_ranks_by_absolute_contribution():
    result = attribution.attribute(TEXT, keyword_score, method="occlusion")
    assert [token for token, _ in result.top(2)] == ["France", "Paris"]


def test_normalised_scales_to_the_largest_magnitude():
    result = attribution.attribute(TEXT, keyword_score, method="occlusion")
    assert max(result.normalised()) == 1.0
    assert dict(zip(result.tokens, result.normalised()))["Paris"] == 0.5


def test_normalised_survives_an_all_zero_attribution():
    result = attribution.attribute(TEXT, lambda text: 1.0, method="occlusion")
    assert result.normalised() == [0.0] * len(result.tokens)


def test_a_negative_contribution_is_kept():
    result = attribution.attribute(
        "good bad", lambda text: 1.0 - ("bad" in text), method="occlusion"
    )
    assert dict(zip(result.tokens, result.scores))["bad"] == -1.0


def test_empty_text_is_rejected():
    with pytest.raises(ValueError, match="empty text"):
        attribution.attribute("   ", keyword_score)


def test_auto_falls_back_to_occlusion_without_shap(monkeypatch):
    monkeypatch.setitem(sys.modules, "shap", None)
    assert attribution.attribute(TEXT, keyword_score, method="auto").method == "occlusion"


def test_asking_for_shap_without_shap_says_what_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "shap", None)
    with pytest.raises(ImportError, match="pip install evalforge\\[attribution\\]"):
        attribution.attribute(TEXT, keyword_score, method="shap")


def test_an_unknown_method_is_rejected():
    with pytest.raises(ValueError, match="must be 'auto', 'occlusion' or 'shap'"):
        attribution.attribute(TEXT, keyword_score, method="gradients")


def test_one_score_call_per_token_plus_the_baseline():
    calls = []

    def counted(text):
        calls.append(text)
        return keyword_score(text)

    result = attribution.attribute(TEXT, counted, method="occlusion")
    assert len(calls) == len(result.tokens) + 1


def test_save_and_read_back(tmp_path):
    result = attribution.attribute(TEXT, keyword_score, method="occlusion", span_id="s1")

    with Store(tmp_path / "evalforge.db") as store:
        attribution.save(store, result)
        loaded = attribution.for_span(store, "s1")

        assert loaded.tokens == result.tokens
        assert loaded.scores == result.scores
        assert loaded.baseline == 1.5
        assert loaded.method == "occlusion"


def test_reading_a_span_with_no_attribution(tmp_path):
    with Store(tmp_path / "evalforge.db") as store:
        assert attribution.for_span(store, "missing") is None
