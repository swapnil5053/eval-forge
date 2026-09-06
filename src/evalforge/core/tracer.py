"""The @trace decorator."""

import contextvars
import dataclasses
import functools
import inspect
import logging
import traceback
from typing import Any, Callable, Optional, Set

from . import context, cost, models, spool

LOGGER = logging.getLogger(__name__)

# Return values already priced by a descendant span, so a function that merely
# passes its child's LLM response along does not get those tokens counted twice.
# Keyed by identity *and* usage: an id on its own can be recycled by the allocator
# once the earlier object is collected.
_priced_outputs: contextvars.ContextVar[Optional[Set[tuple]]] = contextvars.ContextVar(
    "evalforge_priced_outputs", default=None
)


@dataclasses.dataclass(frozen=True)
class _Options:
    name: Optional[str] = None
    type: str = "general"
    tags: Optional[dict] = None
    metadata: Optional[dict] = None
    capture_input: bool = True
    capture_output: bool = True


@dataclasses.dataclass
class _ActiveSpan:
    span: models.Span
    tokens: context.ContextTokens
    trace: Optional[models.Trace]
    priced_token: Optional[contextvars.Token] = None


def trace(
    name: Any = None,
    *,
    type: str = "general",
    tags: Optional[dict] = None,
    metadata: Optional[dict] = None,
    capture_input: bool = True,
    capture_output: bool = True,
) -> Callable:
    """Record every call of the decorated function as a span.

    Usable bare (``@trace``) or configured (``@trace(name="retrieval")``). Nested
    calls become child spans of the enclosing one; the outermost call opens the
    trace. A span whose return value carries OpenAI-style token usage is recorded
    as type ``llm`` and priced through :mod:`evalforge.core.cost`.
    """
    options = _Options(
        name=None if callable(name) else name,
        type=type,
        tags=tags,
        metadata=metadata,
        capture_input=capture_input,
        capture_output=capture_output,
    )

    if callable(name):
        return _wrap(name, options)

    def decorator(func: Callable) -> Callable:
        return _wrap(func, options)

    return decorator


def _wrap(func: Callable, options: _Options) -> Callable:
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            active = _begin(func, options, args, kwargs)
            try:
                output = await func(*args, **kwargs)
            except BaseException as error:
                _end(active, None, error, options)
                raise
            _end(active, output, None, options)
            return output

        return async_wrapper

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        active = _begin(func, options, args, kwargs)
        try:
            output = func(*args, **kwargs)
        except BaseException as error:
            _end(active, None, error, options)
            raise
        _end(active, output, None, options)
        return output

    return wrapper


def _begin(func: Callable, options: _Options, args: tuple, kwargs: dict) -> _ActiveSpan:
    name = options.name or _span_name(func)
    root = context.is_root()
    trace_id = context.current_trace_id() or models.new_id()

    span = models.Span(
        id=models.new_id(),
        trace_id=trace_id,
        name=name,
        parent_span_id=context.current_span_id(),
        type=options.type,
        input=_capture_inputs(func, args, kwargs) if options.capture_input else None,
        tags=dict(options.tags or {}),
        metadata=dict(options.metadata or {}),
    )
    trace_record = (
        models.Trace(id=trace_id, name=name, start_time=span.start_time, tags=span.tags)
        if root
        else None
    )

    writer = spool.get_writer()
    if trace_record is not None:
        writer.write(trace_record.to_spool_dict("trace_start"))
    writer.write(span.to_spool_dict("span_start"))

    return _ActiveSpan(
        span=span,
        tokens=context.enter_span(span.id, trace_id),
        trace=trace_record,
        priced_token=_priced_outputs.set(set()) if root else None,
    )


def _end(
    active: _ActiveSpan, output: Any, error: Optional[BaseException], options: _Options
) -> None:
    span = active.span
    span.end_time = models.utcnow()

    if error is not None:
        span.status = "error"
        span.error = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
    elif options.capture_output:
        span.output = output

    if error is None:
        _record_usage(span, output)

    context.exit_span(active.tokens)

    writer = spool.get_writer()
    writer.write(span.to_spool_dict("span_end"))

    if active.trace is not None:
        active.trace.end_time = span.end_time
        active.trace.status = span.status
        writer.write(active.trace.to_spool_dict("trace_end"))
        context.note_finished_trace(active.trace.id)

    if active.priced_token is not None:
        _priced_outputs.reset(active.priced_token)


def _span_name(func: Callable) -> str:
    """Qualified name without the closure noise: 'Pipeline.run', 'retrieve'."""
    return func.__qualname__.rsplit("<locals>.", 1)[-1]


def _capture_inputs(func: Callable, args: tuple, kwargs: dict) -> Optional[dict]:
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
    except TypeError as error:
        LOGGER.debug("could not bind arguments of %s: %s", func.__qualname__, error)
        return None
    bound.apply_defaults()
    captured = dict(bound.arguments)
    captured.pop("self", None)
    captured.pop("cls", None)
    return {key: models.jsonable(value) for key, value in captured.items()}


def _record_usage(span: models.Span, output: Any) -> None:
    model, prompt_tokens, completion_tokens = _extract_usage(output)
    if prompt_tokens is None and completion_tokens is None:
        return

    priced = _priced_outputs.get()
    if priced is not None:
        fingerprint = (id(output), prompt_tokens, completion_tokens)
        if fingerprint in priced:
            return
        priced.add(fingerprint)

    span.model = model
    span.prompt_tokens = prompt_tokens
    span.completion_tokens = completion_tokens
    span.estimated_cost_usd = cost.estimate_cost(model, prompt_tokens, completion_tokens)
    if span.type == "general":
        span.type = "llm"


def _extract_usage(output: Any) -> tuple:
    """Pull (model, prompt_tokens, completion_tokens) out of an LLM response."""
    usage = _field(output, "usage")
    if usage is None:
        return None, None, None

    prompt_tokens = _as_int(_field(usage, "prompt_tokens", "input_tokens"))
    completion_tokens = _as_int(_field(usage, "completion_tokens", "output_tokens"))
    if prompt_tokens is None and completion_tokens is None:
        return None, None, None

    model = _field(output, "model")
    return (model if isinstance(model, str) else None), prompt_tokens, completion_tokens


def _field(container: Any, *names: str) -> Any:
    for name in names:
        if isinstance(container, dict):
            if name in container:
                return container[name]
        else:
            value = getattr(container, name, None)
            if value is not None:
                return value
    return None


def _as_int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
