"""EvalForge - a lightweight LLM evaluation workbench."""

from .core.models import FeedbackScore, Span, Trace
from .core.tracer import trace
from .eval.experiment import evaluate
from .eval.metrics import Score

__version__ = "0.2.0"

__all__ = [
    "FeedbackScore",
    "Score",
    "Span",
    "Trace",
    "evaluate",
    "trace",
    "__version__",
]
