import sys

import pytest

from evalforge.core import cost


@pytest.fixture(autouse=True)
def clear_price_cache():
    cost.reset_cache()
    yield
    cost.reset_cache()


def fake_prices(monkeypatch, table):
    monkeypatch.setattr(cost, "_prices", table)
    monkeypatch.setattr(cost, "_price_lookup_attempted", True)


def test_normalize_model_name():
    assert cost.normalize_model_name("openai/GPT-4o") == "gpt-4o"
    assert cost.normalize_model_name("  Claude-3-Opus  ") == "claude-3-opus"
    assert cost.normalize_model_name("gpt-4o-mini") == "gpt-4o-mini"


def test_estimates_from_price_table(monkeypatch):
    fake_prices(
        monkeypatch,
        {"gpt-4o-mini": {"input_cost_per_token": 1e-6, "output_cost_per_token": 4e-6}},
    )
    assert cost.estimate_cost("gpt-4o-mini", 1000, 500) == pytest.approx(0.003)


def test_falls_back_to_normalized_name(monkeypatch):
    fake_prices(
        monkeypatch,
        {"gpt-4o": {"input_cost_per_token": 2e-6, "output_cost_per_token": 1e-5}},
    )
    assert cost.estimate_cost("openai/GPT-4o", 100, 10) == pytest.approx(0.0003)


def test_unknown_model_returns_none(monkeypatch):
    fake_prices(monkeypatch, {"gpt-4o": {"input_cost_per_token": 1e-6}})
    assert cost.estimate_cost("nonexistent-model", 100, 100) is None


def test_missing_token_counts_return_none(monkeypatch):
    fake_prices(monkeypatch, {"gpt-4o": {"input_cost_per_token": 1e-6}})
    assert cost.estimate_cost("gpt-4o", None, None) is None
    assert cost.estimate_cost(None, 10, 10) is None


def test_partial_usage_is_priced(monkeypatch):
    fake_prices(
        monkeypatch,
        {"gpt-4o": {"input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6}},
    )
    assert cost.estimate_cost("gpt-4o", 1000, None) == pytest.approx(0.001)


def test_without_litellm_estimation_is_disabled(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)
    assert cost.estimate_cost("gpt-4o", 100, 100) is None
