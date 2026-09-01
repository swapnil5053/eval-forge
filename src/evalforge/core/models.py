"""Dataclasses for the objects EvalForge records."""

import dataclasses
import datetime
import logging
import uuid
from typing import Any, Optional

LOGGER = logging.getLogger(__name__)


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def jsonable(value: Any) -> Any:
    """Coerce a value into something json.dumps can serialize."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return jsonable(dataclasses.asdict(value))
    for attribute in ("model_dump", "dict", "to_dict"):
        method = getattr(value, attribute, None)
        if callable(method):
            try:
                return jsonable(method())
            except Exception as error:
                LOGGER.debug("%s.%s() failed, falling back to repr: %s",
                             type(value).__name__, attribute, error)
                break
    return repr(value)


def _spool_dict(record: Any, record_type: str, rename: Optional[dict] = None) -> dict:
    # "type" on the wire is the kind of record. Span's own category travels as
    # "span_type" so the two never collide; ingestion maps it back.
    payload = {"type": record_type}
    rename = rename or {}
    for field in dataclasses.fields(record):
        value = getattr(record, field.name)
        if value is None:
            continue
        payload[rename.get(field.name, field.name)] = jsonable(value)
    return payload


@dataclasses.dataclass
class Span:
    id: str
    trace_id: str
    name: str
    parent_span_id: Optional[str] = None
    type: str = "general"
    start_time: datetime.datetime = dataclasses.field(default_factory=utcnow)
    end_time: Optional[datetime.datetime] = None
    status: str = "ok"
    input: Optional[dict] = None
    output: Any = None
    error: Optional[str] = None
    model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    tags: dict = dataclasses.field(default_factory=dict)
    metadata: dict = dataclasses.field(default_factory=dict)

    @property
    def latency_ms(self) -> Optional[float]:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds() * 1000

    def to_spool_dict(self, record_type: str = "span_end") -> dict:
        return _spool_dict(self, record_type, rename={"type": "span_type"})


@dataclasses.dataclass
class Trace:
    id: str
    name: str
    start_time: datetime.datetime = dataclasses.field(default_factory=utcnow)
    end_time: Optional[datetime.datetime] = None
    status: str = "ok"
    tags: dict = dataclasses.field(default_factory=dict)
    metadata: dict = dataclasses.field(default_factory=dict)

    def to_spool_dict(self, record_type: str = "trace_end") -> dict:
        return _spool_dict(self, record_type)


@dataclasses.dataclass
class FeedbackScore:
    id: str
    span_id: str
    name: str
    value: float
    reason: Optional[str] = None
    source: str = "sdk"
    created_at: datetime.datetime = dataclasses.field(default_factory=utcnow)

    def to_spool_dict(self, record_type: str = "feedback_score") -> dict:
        return _spool_dict(self, record_type)
