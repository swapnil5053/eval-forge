"""The experiment runner.

An experiment is a dataset, a task and a list of metrics. The task runs over the
dataset in a thread pool, each metric scores each result, and everything lands in
DuckDB so the CLI and dashboard can compare runs later.
"""

import concurrent.futures
import dataclasses
import datetime
import inspect
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from ..core import context, spool
from ..core.models import new_id, utcnow
from ..storage.duckdb_store import Store
from ..storage.ingest import ingest_once
from . import dataset as dataset_module
from . import judge
from .metrics import Metric, Score

LOGGER = logging.getLogger(__name__)

# Keys a dataset item may use for the question and the retrieved passages. Metrics
# receive these by name, so a pipeline that uses any of them needs no mapping.
_QUESTION_KEYS = ("input", "question", "query", "prompt")
_CONTEXT_KEYS = ("context", "contexts", "passages", "documents")


@dataclasses.dataclass
class ItemResult:
    dataset_item_id: str
    input: Dict[str, Any]
    output: Any = None
    expected_output: Any = None
    scores: Dict[str, Score] = dataclasses.field(default_factory=dict)
    errors: Dict[str, str] = dataclasses.field(default_factory=dict)
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    trace_id: Optional[str] = None

    @property
    def failed(self) -> bool:
        return self.error is not None or any(score.failed for score in self.scores.values())


@dataclasses.dataclass
class ExperimentResult:
    id: str
    name: str
    dataset_name: Optional[str]
    results: List[ItemResult]
    created_at: datetime.datetime

    @property
    def errors(self) -> int:
        return sum(1 for result in self.results if result.error)

    def means(self) -> Dict[str, float]:
        """Mean of each metric across the items that produced a score."""
        totals: Dict[str, List[float]] = {}
        for result in self.results:
            for name, score in result.scores.items():
                totals.setdefault(name, []).append(score.value)
        return {name: sum(values) / len(values) for name, values in sorted(totals.items())}

    def polarity(self) -> Dict[str, bool]:
        return {
            name: score.higher_is_better
            for result in self.results
            for name, score in result.scores.items()
        }


def evaluate(
    dataset: Union[str, dataset_module.Dataset, Sequence[dict]],
    task: Callable[[Dict[str, Any]], Any],
    metrics: Sequence[Metric] = (),
    name: Optional[str] = None,
    num_workers: int = 4,
    model: str = judge.DEFAULT_MODEL,
    store: Optional[Store] = None,
    db: Optional[str] = None,
) -> ExperimentResult:
    """Run ``task`` over a dataset, score every result, and store the experiment.

    Holds the DuckDB write lock for the duration, so stop ``evalforge ingest --watch``
    or the dashboard first. Traces the task records go through the spool as usual and
    are ingested at the end, which is what links each result to its trace.
    """
    owned = store is None
    store = store or Store(db)
    try:
        found, items = dataset_module.resolve(store, dataset)
        if not items:
            raise ValueError("the dataset is empty, there is nothing to evaluate")

        experiment = ExperimentResult(
            id=new_id(),
            name=name or f"experiment-{utcnow():%Y%m%d-%H%M%S}",
            dataset_name=found.name if found else None,
            results=_run(items, task, num_workers),
            created_at=utcnow(),
        )
        _score(experiment.results, metrics, model, num_workers)

        spool.seal_active()
        ingest_once(store, spool.active_spool_dir())
        _save(store, experiment, found)
        return experiment
    finally:
        if owned:
            store.close()


def _run(
    items: Sequence[dataset_module.DatasetItem],
    task: Callable[[Dict[str, Any]], Any],
    num_workers: int,
) -> List[ItemResult]:
    results = [
        ItemResult(
            dataset_item_id=item.id, input=item.input, expected_output=item.expected_output
        )
        for item in items
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as pool:
        for result in pool.map(lambda pair: _run_one(*pair, task), zip(results, items)):
            LOGGER.debug("ran item %s in %.0fms", result.dataset_item_id, result.latency_ms or 0)
    return results


def _run_one(
    result: ItemResult,
    item: dataset_module.DatasetItem,
    task: Callable[[Dict[str, Any]], Any],
) -> ItemResult:
    started = time.perf_counter()
    try:
        result.output = task(item.input)
    except Exception as error:
        result.error = f"{type(error).__name__}: {error}"
        LOGGER.debug("task failed on item %s: %s", item.id, error)
    result.latency_ms = (time.perf_counter() - started) * 1000
    result.trace_id = context.last_trace_id()
    return result


def _score(
    results: Sequence[ItemResult], metrics: Sequence[Metric], model: str, num_workers: int
) -> None:
    calls = [
        (result, metric)
        for result in results
        if result.error is None
        for metric in metrics
    ]
    if not calls:
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as pool:
        for (result, metric), scored in zip(
            calls, pool.map(lambda call: _score_one(call[0], call[1], model), calls)
        ):
            if isinstance(scored, Score):
                result.scores[scored.metric_name] = scored
            else:
                result.errors[metric.__name__] = scored


def _score_one(result: ItemResult, metric: Metric, model: str) -> Union[Score, str]:
    arguments = _metric_arguments(metric, result, model)
    try:
        return metric(**arguments)
    except Exception as error:
        LOGGER.debug("metric %s failed: %s", metric.__name__, error)
        return f"{type(error).__name__}: {error}"


def _metric_arguments(metric: Metric, result: ItemResult, model: str) -> Dict[str, Any]:
    """Pass a metric only the arguments its signature actually declares."""
    available = {
        "input": _first(result.input, _QUESTION_KEYS) or json.dumps(result.input, default=str),
        "output": _text(result.output),
        "context": _context(result),
        "expected_output": result.expected_output,
        "model": model,
    }
    parameters = inspect.signature(metric).parameters
    return {name: value for name, value in available.items() if name in parameters}


def _context(result: ItemResult) -> List[str]:
    for source in (result.output, result.input):
        found = _first(source, _CONTEXT_KEYS) if isinstance(source, dict) else None
        if found:
            return [found] if isinstance(found, str) else [_text(item) for item in found]
    return []


def _first(mapping: Any, keys: Sequence[str]) -> Any:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        if mapping.get(key):
            return mapping[key]
    return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("output", "answer", "text", "content"):
            if value.get(key):
                return _text(value[key])
        return json.dumps(value, default=str)
    return str(value)


def _save(
    store: Store, experiment: ExperimentResult, found: Optional[dataset_module.Dataset]
) -> None:
    store.upsert(
        "experiments",
        [
            {
                "id": experiment.id,
                "name": experiment.name,
                "dataset_id": found.id if found else "(ad-hoc)",
                "created_at": experiment.created_at,
                "metadata": {"metrics": sorted(experiment.means())},
            }
        ],
    )
    store.upsert(
        "experiment_results",
        [
            {
                "id": new_id(),
                "experiment_id": experiment.id,
                "dataset_item_id": result.dataset_item_id,
                "trace_id": result.trace_id,
                "output": result.output,
                "scores": {
                    name: dataclasses.asdict(score) for name, score in result.scores.items()
                }
                | {name: {"error": message} for name, message in result.errors.items()},
                "latency_ms": result.latency_ms,
                "error": result.error,
                "created_at": experiment.created_at,
            }
            for result in experiment.results
        ],
    )
