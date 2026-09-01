"""EvalForge - a lightweight LLM evaluation workbench."""

from .core.models import FeedbackScore, Span, Trace
from .core.tracer import trace

__version__ = "0.1.0"

__all__ = ["FeedbackScore", "Span", "Trace", "trace", "__version__"]
