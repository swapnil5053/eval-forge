"""Reflex state: everything the panel shows, refreshed on a timer."""

import logging
from typing import Any, Dict, List

import reflex as rx

from ..eval import faithfulness_audit
from ..storage import queries
from ..storage.duckdb_store import DatabaseLocked
from . import data

LOGGER = logging.getLogger(__name__)

REFRESH_MS = 5000
WINDOW_HOURS = 24
SERIES_DAYS = 7


class Panel(rx.State):
    """One state for the whole panel. Reads only; writes go through the spool."""

    connected: bool = False
    footer: Dict[str, str] = {"traces": data.EMPTY, "updated": data.EMPTY, "size": data.EMPTY}

    summary: Dict[str, Any] = dict(data.EMPTY_SUMMARY)
    volume: List[Dict[str, Any]] = []
    latency: List[Dict[str, Any]] = []
    tokens_by_model: List[Dict[str, Any]] = []
    cost_by_function: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    traces: List[Dict[str, Any]] = []
    total: int = 0
    page: int = 0
    sort: str = "started"
    descending: bool = True
    search: str = ""

    expanded_trace: str = ""
    spans: List[Dict[str, Any]] = []
    experiments: List[Dict[str, Any]] = []
    experiment_name: str = ""
    experiment_means: List[Dict[str, str]] = []
    experiment_metrics: List[str] = []
    experiment_items: List[Dict[str, Any]] = []
    compare_with: str = ""
    comparison: List[Dict[str, Any]] = []

    datasets: List[Dict[str, str]] = []
    dataset_name: str = ""
    dataset_items: List[Dict[str, str]] = []

    audits: List[Dict[str, Any]] = []
    audit_id: str = ""
    audit: Dict[str, str] = {}
    audit_claims: List[Dict[str, Any]] = []

    expanded_span: str = ""
    input_parts: List[Dict[str, str]] = []
    output_parts: List[Dict[str, str]] = []
    attribution: List[Dict[str, str]] = []

    @rx.var
    def experiment_choices(self) -> List[str]:
        return [row["name"] for row in self.experiments]

    @rx.var
    def comparing(self) -> bool:
        return bool(self.compare_with) and self.compare_with != self.experiment_name

    @rx.var
    def page_label(self) -> str:
        if not self.total:
            return data.EMPTY
        first = self.page * data.PAGE_SIZE + 1
        return f"{first}-{min(first + data.PAGE_SIZE - 1, self.total)} / {self.total}"

    @rx.var
    def has_previous(self) -> bool:
        return self.page > 0

    @rx.var
    def has_next(self) -> bool:
        return (self.page + 1) * data.PAGE_SIZE < self.total

    def refresh(self) -> None:
        """Reload everything from the database. Safe to call on a timer."""
        if not data.database_exists():
            self.connected = False
            return
        try:
            with data.read_only_store() as store:
                self._load(store)
            self.connected = True
        except DatabaseLocked as error:
            LOGGER.debug("database busy, keeping the last reading: %s", error)

    def sort_by(self, column: str) -> None:
        self.descending = not self.descending if self.sort == column else True
        self.sort = column
        self.page = 0
        self.refresh()

    def set_query(self, value: str) -> None:
        self.search = value
        self.page = 0
        self.refresh()

    def next_page(self) -> None:
        if self.has_next:
            self.page += 1
            self.refresh()

    def previous_page(self) -> None:
        if self.has_previous:
            self.page -= 1
            self.refresh()

    def open_experiment(self, name: str) -> None:
        self.experiment_name = "" if self.experiment_name == name else name
        self.compare_with = ""
        self.comparison = []
        self.refresh()

    def set_compare_with(self, name: str) -> None:
        self.compare_with = name
        self.refresh()

    def open_dataset(self, name: str) -> None:
        self.dataset_name = "" if self.dataset_name == name else name
        self.refresh()

    def open_audit(self, audit_id: str) -> None:
        self.audit_id = "" if self.audit_id == audit_id else audit_id
        self.audit = {}
        self.audit_claims = []
        self.refresh()

    def toggle_trace(self, trace_id: str) -> None:
        self.expanded_span = ""
        self.attribution = []
        if self.expanded_trace == trace_id:
            self.expanded_trace = ""
            self.spans = []
            return
        self.expanded_trace = trace_id
        self.refresh()

    def toggle_span(self, span_id: str) -> None:
        self.expanded_span = "" if self.expanded_span == span_id else span_id
        self.attribution = []
        self.input_parts = []
        self.output_parts = []
        if self.expanded_span:
            self.refresh()

    def _load(self, store) -> None:
        self.summary = data.summary(store, hours=WINDOW_HOURS)
        series = queries.daily_series(store, days=SERIES_DAYS)
        self.volume = data.volume_series(series)
        self.latency = data.latency_series(series)
        self.tokens_by_model = data.group_rows(
            queries.token_usage(store, hours=WINDOW_HOURS), "tokens"
        )
        self.cost_by_function = data.group_rows(
            queries.cost_breakdown(store, hours=WINDOW_HOURS), "cost"
        )
        self.errors = data.error_rows(queries.recent_errors(store))

        self.total = queries.count_traces(store, self.search)
        self.traces = data.trace_rows(
            queries.browse_traces(
                store,
                limit=data.PAGE_SIZE,
                offset=self.page * data.PAGE_SIZE,
                sort=self.sort,
                descending=self.descending,
                search=self.search,
            )
        )

        if self.expanded_trace:
            _, spans = queries.trace_detail(store, self.expanded_trace)
            self.spans = data.span_tree(spans)
        if self.expanded_span:
            self.attribution = data.attribution_row(store, self.expanded_span)
            opened = next(
                (span for span in self.spans if span["id"] == self.expanded_span), None
            )
            self.input_parts = data.json_parts(opened["input"]) if opened else []
            self.output_parts = data.json_parts(opened["output"]) if opened else []

        self._load_experiments(store)
        self._load_datasets(store)
        self._load_audits(store)
        self.footer = data.footer(store)

    def _load_experiments(self, store) -> None:
        rows = queries.experiments(store)
        self.experiments = data.experiment_rows(rows)
        if not self.experiment_name:
            self.experiment_means = []
            self.experiment_metrics = []
            self.experiment_items = []
            self.comparison = []
            return

        opened = queries.experiment(store, self.experiment_name)
        self.experiment_means = data.metric_means(opened)
        self.experiment_metrics = opened.metrics if opened else []
        self.experiment_items = data.experiment_item_rows(
            queries.experiment_items(store, self.experiment_name),
            self.experiment_metrics,
            opened.polarity if opened else {},
        )
        self.comparison = (
            data.comparison_rows(
                queries.compare_experiments(store, self.experiment_name, self.compare_with),
                self.experiment_name,
                self.compare_with,
            )
            if self.comparing
            else []
        )

    def _load_datasets(self, store) -> None:
        self.datasets = data.dataset_rows(queries.datasets(store))
        self.dataset_items = (
            data.dataset_item_rows(queries.dataset_items(store, self.dataset_name))
            if self.dataset_name
            else []
        )

    def _load_audits(self, store) -> None:
        self.audits = data.audit_rows(faithfulness_audit.recent(store, limit=50))
        if not self.audit_id:
            return
        found = faithfulness_audit.load(store, self.audit_id)
        if found is None:
            self.audit_id = ""
            return
        self.audit = data.audit_header(found)
        self.audit_claims = data.audit_claim_rows(found)
