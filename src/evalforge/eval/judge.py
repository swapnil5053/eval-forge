"""The LLM judge.

One function calls one provider-agnostic completion API. LiteLLM handles every
provider - OpenAI, Anthropic, a local Ollama - so nothing here knows about any
of them, and a judge can be pointed at ``ollama/llama3`` to run offline.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

LOGGER = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("EVALFORGE_JUDGE_MODEL", "gpt-4o-mini")

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class JudgeError(RuntimeError):
    """The judge could not produce a usable answer."""


def complete(system: str, user: str, model: str = DEFAULT_MODEL, temperature: float = 0.0) -> str:
    """Send one system/user exchange to the judge model and return its text."""
    try:
        import litellm
    except ImportError as error:
        raise JudgeError(
            "LLM-as-a-judge metrics need litellm. Install it with "
            "'pip install evalforge[eval]', or pass a model your own judge handles."
        ) from error

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    response = litellm.completion(model=model, messages=messages, temperature=temperature)
    content = response.choices[0].message.content
    if not content:
        raise JudgeError(f"{model} returned an empty response")
    return content


def judge_json(
    system: str,
    user: str,
    model: str = DEFAULT_MODEL,
    required: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Call the judge and parse its answer as a JSON object."""
    content = complete(system, user, model=model)
    payload = parse_json(content)
    for key in required or []:
        if key not in payload:
            raise JudgeError(f"judge response is missing {key!r}: {content[:200]}")
    return payload


def parse_json(content: str) -> Dict[str, Any]:
    """Read a JSON object out of a model response, fenced or not."""
    candidates = [content]
    fenced = _FENCE.search(content)
    if fenced:
        candidates.insert(0, fenced.group(1))
    embedded = _OBJECT.search(content)
    if embedded:
        candidates.append(embedded.group(0))

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload

    raise JudgeError(f"judge did not return a JSON object: {content[:200]}")


def unit_score(payload: Dict[str, Any], key: str = "score") -> float:
    """Read a 0-1 score out of a judge payload, rejecting anything outside the range."""
    try:
        score = float(payload[key])
    except (KeyError, TypeError, ValueError) as error:
        raise JudgeError(f"judge response has no numeric {key!r}: {payload}") from error
    if not 0.0 <= score <= 1.0:
        raise JudgeError(f"{key} must be between 0.0 and 1.0, got {score}")
    return score


def as_reason(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value) if value is not None else ""
