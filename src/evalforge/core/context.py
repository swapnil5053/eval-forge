"""Trace and span context propagation.

The active span stack lives in a ContextVar holding an immutable tuple, so each
thread and each asyncio task sees its own stack without any locking. A child
thread started with ``threading.Thread`` inherits the context of its parent;
``ThreadPoolExecutor`` workers do NOT, because the pool's threads outlive any
single submission. To trace inside a pool, capture the context at submit time
with ``contextvars.copy_context()`` and run the callable through it.
"""

import contextvars
from typing import NamedTuple, Optional, Tuple

_span_stack: contextvars.ContextVar[Tuple[str, ...]] = contextvars.ContextVar(
    "evalforge_span_stack", default=()
)
_trace_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "evalforge_trace_id", default=None
)


class ContextTokens(NamedTuple):
    span: contextvars.Token
    trace: Optional[contextvars.Token]


def current_span_id() -> Optional[str]:
    stack = _span_stack.get()
    return stack[-1] if stack else None


def current_trace_id() -> Optional[str]:
    return _trace_id.get()


def is_root() -> bool:
    """True when no span is active, so the next span opens a new trace."""
    return not _span_stack.get()


def enter_span(span_id: str, trace_id: str) -> ContextTokens:
    trace_token = _trace_id.set(trace_id) if _trace_id.get() is None else None
    span_token = _span_stack.set(_span_stack.get() + (span_id,))
    return ContextTokens(span=span_token, trace=trace_token)


def exit_span(tokens: ContextTokens) -> None:
    _span_stack.reset(tokens.span)
    if tokens.trace is not None:
        _trace_id.reset(tokens.trace)
