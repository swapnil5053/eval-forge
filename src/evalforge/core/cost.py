"""Token cost estimation.

Prices come from ``litellm.model_cost`` at import time rather than a vendored
price table, so they track LiteLLM's releases instead of going stale in this
repository. LiteLLM is an optional dependency: without it every estimate is
None and nothing raises.
"""

import logging
from typing import Optional

LOGGER = logging.getLogger(__name__)

_prices: Optional[dict] = None
_price_lookup_attempted = False


def _model_prices() -> Optional[dict]:
    global _prices, _price_lookup_attempted
    if not _price_lookup_attempted:
        _price_lookup_attempted = True
        try:
            import litellm
        except ImportError:
            LOGGER.debug("litellm is not installed; cost estimation is disabled")
        else:
            _prices = litellm.model_cost
    return _prices


def normalize_model_name(model: str) -> str:
    """Strip a provider prefix and lowercase, e.g. 'OpenAI/GPT-4o' -> 'gpt-4o'."""
    return model.strip().lower().rsplit("/", 1)[-1]


def _price_entry(model: str, prices: dict) -> Optional[dict]:
    for candidate in (model, model.lower(), normalize_model_name(model)):
        entry = prices.get(candidate)
        if entry is not None:
            return entry
    return None


def estimate_cost(
    model: Optional[str],
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
) -> Optional[float]:
    """Return the estimated cost in USD, or None if the model or prices are unknown."""
    if not model or (prompt_tokens is None and completion_tokens is None):
        return None

    prices = _model_prices()
    if prices is None:
        return None

    entry = _price_entry(model, prices)
    if entry is None:
        LOGGER.debug("no price entry for model %s", model)
        return None

    input_price = entry.get("input_cost_per_token") or 0.0
    output_price = entry.get("output_cost_per_token") or 0.0
    return (prompt_tokens or 0) * input_price + (completion_tokens or 0) * output_price


def reset_cache() -> None:
    """Forget the cached price table. Tests use this to simulate a missing litellm."""
    global _prices, _price_lookup_attempted
    _prices = None
    _price_lookup_attempted = False
