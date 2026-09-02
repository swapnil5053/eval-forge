"""Token-level input attribution.

Which words in a prompt actually drove the score you care about? Both methods here
answer that by perturbing the input and watching a score move, so they work on any
API model - no logits, no gradients, no local weights.

- ``occlusion`` (always available): drop one token at a time and measure the drop.
  One score call per token, plus one baseline.
- ``shap`` (needs ``pip install evalforge[attribution]``): SHAP's partition
  explainer, which accounts for interactions between neighbouring tokens instead of
  assuming independence. Slower, and worth it when tokens matter in combination.

The score function is yours: a judge metric, a similarity to a reference answer, a
classifier probability. Attribution only asks that the same input always scores the
same, so cache it if the underlying call is expensive.
"""

import dataclasses
import datetime
import importlib.util
import json
import logging
import re
from typing import Callable, List, Optional, Sequence

from ..core.models import new_id, utcnow
from ..storage import queries
from ..storage.duckdb_store import Store

LOGGER = logging.getLogger(__name__)

ScoreFunction = Callable[[str], float]

_TOKEN = re.compile(r"\S+")


@dataclasses.dataclass
class Attribution:
    id: str
    text: str
    tokens: List[str]
    scores: List[float]
    method: str
    baseline: float
    created_at: datetime.datetime
    span_id: Optional[str] = None
    trace_id: Optional[str] = None

    def top(self, count: int = 10) -> List[tuple]:
        """The most influential tokens, largest absolute contribution first."""
        ranked = sorted(
            zip(self.tokens, self.scores), key=lambda pair: abs(pair[1]), reverse=True
        )
        return ranked[:count]

    def normalised(self) -> List[float]:
        """Scores rescaled to -1..1 by the largest magnitude, for highlighting."""
        largest = max((abs(score) for score in self.scores), default=0.0)
        return [score / largest for score in self.scores] if largest else list(self.scores)


def tokenize(text: str) -> List[str]:
    return _TOKEN.findall(text)


def attribute(
    text: str,
    score_fn: ScoreFunction,
    method: str = "auto",
    span_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> Attribution:
    """Attribute ``score_fn(text)`` to the individual tokens of ``text``."""
    tokens = tokenize(text)
    if not tokens:
        raise ValueError("cannot attribute an empty text")

    resolved = _resolve_method(method)
    baseline = float(score_fn(text))
    scores = (
        _shap_scores(tokens, score_fn) if resolved == "shap" else _occlusion_scores(tokens, score_fn, baseline)
    )

    return Attribution(
        id=new_id(),
        text=text,
        tokens=tokens,
        scores=scores,
        method=resolved,
        baseline=baseline,
        created_at=utcnow(),
        span_id=span_id,
        trace_id=trace_id,
    )


def _resolve_method(method: str) -> str:
    if method == "occlusion":
        return method
    if method in ("shap", "auto"):
        if _shap_available():
            return "shap"
        if method == "shap":
            raise ImportError(
                "the shap method needs shap and numpy. Install them with "
                "'pip install evalforge[attribution]', or pass method='occlusion'."
            )
        LOGGER.debug("shap is not installed, falling back to occlusion")
        return "occlusion"
    raise ValueError(f"method must be 'auto', 'occlusion' or 'shap', got {method!r}")


def _shap_available() -> bool:
    return importlib.util.find_spec("shap") is not None


def _occlusion_scores(
    tokens: Sequence[str], score_fn: ScoreFunction, baseline: float
) -> List[float]:
    scores = []
    for index in range(len(tokens)):
        without = " ".join(tokens[:index] + tokens[index + 1 :])
        scores.append(baseline - float(score_fn(without)))
    return scores


def _shap_scores(tokens: Sequence[str], score_fn: ScoreFunction) -> List[float]:
    import numpy
    import shap

    def masked(mask_matrix, _unused):
        return numpy.array(
            [
                score_fn(" ".join(token for token, keep in zip(tokens, mask) if keep))
                for mask in mask_matrix
            ]
        )

    explainer = shap.Explainer(masked, shap.maskers.Independent)
    values = explainer(numpy.ones((1, len(tokens))))
    return [float(value) for value in values.values[0]]


def save(store: Store, attribution: Attribution) -> None:
    store.upsert(
        "token_attributions",
        [
            {
                "id": attribution.id,
                "span_id": attribution.span_id,
                "trace_id": attribution.trace_id,
                "method": attribution.method,
                "text": attribution.text,
                "tokens": attribution.tokens,
                "scores": attribution.scores,
                "baseline": attribution.baseline,
                "created_at": attribution.created_at,
            }
        ],
    )


def for_span(store: Store, span_id: str) -> Optional[Attribution]:
    row = store.db.execute(
        """
        SELECT id, text, tokens, scores, method, baseline, epoch_ms(created_at),
               span_id, trace_id
        FROM token_attributions WHERE span_id = ? ORDER BY created_at DESC LIMIT 1
        """,
        [span_id],
    ).fetchone()
    if row is None:
        return None

    identifier, text, tokens, scores, method, baseline, created_ms, span, trace = row
    return Attribution(
        id=identifier,
        text=text,
        tokens=json.loads(tokens),
        scores=json.loads(scores),
        method=method,
        baseline=baseline,
        created_at=queries.moment(created_ms),
        span_id=span,
        trace_id=trace,
    )
