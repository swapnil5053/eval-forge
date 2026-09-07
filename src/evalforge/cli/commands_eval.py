"""The 'evalforge eval' and 'evalforge audit' commands."""

import importlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
import yaml
from rich.table import Table

from ..eval import dataset as dataset_module
from ..eval import faithfulness_audit, metrics
from ..eval.experiment import ExperimentResult, evaluate
from ..eval.judge import DEFAULT_MODEL
from ..storage import queries
from ..storage.duckdb_store import Store
from .support import brief as _brief
from .support import console
from .support import read_only_store as _read_only

VERDICT_COLOURS = {
    faithfulness_audit.SUPPORTED: "green",
    faithfulness_audit.PARTIALLY_SUPPORTED: "yellow",
    faithfulness_audit.UNSUPPORTED: "red",
    faithfulness_audit.CONTRADICTED: "bold red",
}


@click.group("eval")
def eval_group() -> None:
    """Run and inspect experiments."""


@eval_group.command("run")
@click.argument("config", type=click.Path(exists=True, path_type=Path))
def eval_run(config: Path) -> None:
    """Run the experiment described by a YAML CONFIG file."""
    spec = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    for key in ("dataset", "task"):
        if key not in spec:
            raise click.ClickException(f"{config} is missing required key {key!r}")

    task = _import_callable(spec["task"])
    chosen = [_metric(name) for name in spec.get("metrics", [])]

    experiment = evaluate(
        dataset=spec["dataset"],
        task=task,
        metrics=chosen,
        name=spec.get("name"),
        num_workers=int(spec.get("workers", 4)),
        model=spec.get("model", DEFAULT_MODEL),
    )
    _print_experiment(experiment)


@eval_group.command("list")
def eval_list() -> None:
    """List stored experiments."""
    with _read_only() as store:
        rows = store.db.execute(
            """
            SELECT e.name, coalesce(d.name, '(ad-hoc)'), count(r.id),
                   epoch_ms(e.created_at)
            FROM experiments e
            LEFT JOIN datasets d ON d.id = e.dataset_id
            LEFT JOIN experiment_results r ON r.experiment_id = e.id
            GROUP BY ALL
            ORDER BY 4 DESC
            """
        ).fetchall()

    if not rows:
        console.print("[yellow]no experiments yet[/yellow]")
        return

    table = Table(title="Experiments", header_style="dim")
    for column in ("name", "dataset", "items", "run at"):
        table.add_column(column)
    for name, dataset_name, items, created_ms in rows:
        table.add_row(
            name,
            dataset_name,
            str(items),
            queries.moment(created_ms).astimezone().strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


@eval_group.command("show")
@click.argument("name")
def eval_show(name: str) -> None:
    """Show per-item results for the experiment NAME."""
    with _read_only() as store:
        rows = store.db.execute(
            """
            SELECT r.dataset_item_id, r.output, r.scores, r.latency_ms, r.error
            FROM experiments e
            JOIN experiment_results r ON r.experiment_id = e.id
            WHERE e.name = ?
            ORDER BY r.dataset_item_id
            """,
            [name],
        ).fetchall()

    if not rows:
        raise click.ClickException(f"no experiment named {name!r}")

    parsed = [
        (
            item_id,
            json.loads(output) if output else None,
            json.loads(scores or "{}"),
            latency,
            error,
        )
        for item_id, output, scores, latency, error in rows
    ]
    metric_names = sorted({key for _, _, scores, _, _ in parsed for key in scores})

    table = Table(title=name, header_style="dim")
    table.add_column("item", style="dim", no_wrap=True)
    table.add_column("output", max_width=48)
    for metric_name in metric_names:
        table.add_column(metric_name, justify="right")
    table.add_column("latency", justify="right")

    for item_id, output, scores, latency, error in parsed:
        cells = [item_id[:8], f"[red]{error}[/red]" if error else _brief(output)]
        for metric_name in metric_names:
            cells.append(_score_cell(scores.get(metric_name)))
        cells.append(f"{latency:.0f}ms" if latency else "-")
        table.add_row(*cells)
    console.print(table)


@eval_group.command("gate")
@click.argument("name")
@click.option("--baseline", required=True, help="Experiment to compare against.")
@click.option(
    "--max-drop", default=0.02, show_default=True,
    help="How far a metric may move the wrong way before the gate fails.",
)
@click.option("--metric", "only", multiple=True, help="Gate on this metric only. Repeatable.")
def eval_gate(name: str, baseline: str, max_drop: float, only: tuple) -> None:
    """Fail if NAME regressed against --baseline. Exits 1 so CI can stop a merge.

    Which direction counts as a regression comes from each score's own polarity,
    so hallucination going up fails for the same reason faithfulness going down does.
    """
    if max_drop < 0:
        raise click.BadParameter("--max-drop is a distance, so it cannot be negative.")

    with _read_only() as store:
        runs = {row.name: row for row in queries.experiments(store)}

    for wanted in (name, baseline):
        if wanted not in runs:
            raise click.ClickException(
                f"no experiment named {wanted!r}. Run 'evalforge eval list' to see what is stored."
            )

    opened, was = runs[name], runs[baseline]
    shared = sorted(set(opened.means) & set(was.means) & (set(only) or set(opened.means)))
    if not shared:
        raise click.ClickException(
            f"{name!r} and {baseline!r} share no metric to compare"
            + (f" among {', '.join(only)}." if only else ".")
        )

    table = Table(box=None, pad_edge=False)
    for column in ("metric", baseline, name, "delta", ""):
        table.add_column(column, justify="right" if column != "metric" else "left")

    regressed = []
    for metric in shared:
        before, after = was.means[metric], opened.means[metric]
        higher_is_better = opened.polarity.get(metric, True)
        # Movement in the direction the metric wants, whichever direction that is.
        gained = (after - before) if higher_is_better else (before - after)
        failed = gained < -max_drop
        if failed:
            regressed.append(metric)
        table.add_row(
            metric,
            f"{before:.3f}",
            f"{after:.3f}",
            f"{gained:+.3f}",
            "[red]FAIL[/red]" if failed else "[dim]ok[/dim]",
        )

    console.print(table)
    if not regressed:
        console.print(f"\n[dim]no metric moved more than {max_drop:.3f} the wrong way[/dim]")
        return

    plural = "s" if len(regressed) > 1 else ""
    console.print(
        f"\n[red]{len(regressed)} metric{plural} regressed past {max_drop:.3f}:[/red] "
        + ", ".join(regressed)
    )
    raise SystemExit(1)


@eval_group.command("datasets")
def eval_datasets() -> None:
    """List stored datasets."""
    with _read_only() as store:
        rows = dataset_module.listing(store)

    if not rows:
        console.print("[yellow]no datasets yet[/yellow]")
        return

    table = Table(title="Datasets", header_style="dim")
    for column in ("name", "items", "description"):
        table.add_column(column)
    for row in rows:
        table.add_row(row["name"], str(row["items"]), row["description"] or "")
    console.print(table)


@click.group("audit")
def audit_group() -> None:
    """Run and inspect faithfulness audits."""


@audit_group.command("run")
@click.argument("trace_id")
@click.option("--model", default=DEFAULT_MODEL, show_default=True, help="Judge model.")
def audit_run(trace_id: str, model: str) -> None:
    """Audit the RAG trace TRACE_ID claim by claim. An id prefix is enough."""
    with Store() as store:
        try:
            report = faithfulness_audit.audit_trace(store, trace_id, model=model)
        except (LookupError, ValueError) as error:
            raise click.ClickException(str(error)) from error
        faithfulness_audit.save(store, report)
    _print_audit(report)


@audit_group.command("list")
@click.option("--limit", default=20, show_default=True, help="Rows to show.")
def audit_list(limit: int) -> None:
    """List saved audits."""
    with _read_only() as store:
        rows = faithfulness_audit.recent(store, limit=limit)

    if not rows:
        console.print("[yellow]no audits yet - run 'evalforge audit run <trace-id>'[/yellow]")
        return

    table = Table(title="Faithfulness audits", header_style="dim")
    for column in ("id", "trace", "query", "score", "claims", "unsupported", "contradicted"):
        table.add_column(column)
    for row in rows:
        table.add_row(
            row["id"][:8],
            (row["trace_id"] or "")[:8],
            _brief(row["query"], 40),
            _score_text(row["score"]),
            str(row["claim_count"]),
            str(row["unsupported"]),
            str(row["contradicted"]),
        )
    console.print(table)


@audit_group.command("show")
@click.argument("audit_id")
def audit_show(audit_id: str) -> None:
    """Show one audit claim by claim. An id prefix is enough."""
    with _read_only() as store:
        try:
            report = faithfulness_audit.load(store, audit_id)
        except ValueError as error:
            raise click.ClickException(str(error)) from error
    if report is None:
        raise click.ClickException(f"no audit matching {audit_id!r}")
    _print_audit(report)


def _print_experiment(result: ExperimentResult) -> None:
    means = result.means()
    polarity = result.polarity()

    summary = Table(title=result.name, box=None, header_style="dim", pad_edge=False)
    summary.add_column("metric")
    summary.add_column("mean", justify="right")
    summary.add_column("", style="dim")
    for name, mean in means.items():
        direction = "higher is better" if polarity.get(name, True) else "lower is better"
        summary.add_row(name, f"{mean:.3f}", direction)
    summary.add_row("items", str(len(result.results)), "")
    if result.errors:
        summary.add_row("task errors", f"[red]{result.errors}[/red]", "")
    console.print(summary)

    failing = [item for item in result.results if item.failed]
    if not failing:
        return

    console.print(f"\n[yellow]{len(failing)} item(s) need a look[/yellow]")
    for item in failing[:10]:
        if item.error:
            console.print(f"  [red]{item.error}[/red]  {_brief(item.input, 60)}")
            continue
        worst = sorted(item.scores.values(), key=lambda score: score.value)
        detail = ", ".join(
            f"{score.metric_name}={score.value:.2f}" for score in worst if score.failed
        )
        console.print(f"  {_brief(item.input, 60)}  [yellow]{detail}[/yellow]")


def _print_audit(result: faithfulness_audit.FaithfulnessAudit) -> None:
    console.print(
        f"\n[bold]faithfulness {result.score:.2f}[/bold]  "
        f"{len(result.claims)} claims  "
        f"[red]{result.count(faithfulness_audit.UNSUPPORTED)} unsupported[/red]  "
        f"[bold red]{result.count(faithfulness_audit.CONTRADICTED)} contradicted[/bold red]"
    )
    console.print(f"[dim]{result.id}  query:[/dim] {_brief(result.query, 80)}\n")

    for claim in sorted(result.claims, key=lambda item: item.severity, reverse=True):
        colour = VERDICT_COLOURS[claim.verdict]
        console.print(f"[{colour}]{claim.verdict:<20}[/{colour}] {claim.claim}")
        if claim.rationale:
            console.print(f"[dim]{'':<20} {claim.rationale}[/dim]")
        for passage in result.evidence_for(claim):
            console.print(f"[dim]{'':<20} evidence: {_brief(passage, 90)}[/dim]")


def _metric(name: str):
    try:
        return metrics.get(name)
    except ValueError as error:
        raise click.ClickException(str(error)) from error


def _import_callable(path: str):
    if ":" not in path:
        raise click.ClickException(
            f"task must look like 'module.path:function', got {path!r}"
        )
    module_name, _, attribute = path.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise click.ClickException(f"could not import {module_name!r}: {error}") from error
    try:
        return getattr(module, attribute)
    except AttributeError as error:
        raise click.ClickException(
            f"{module_name!r} has no attribute {attribute!r}"
        ) from error


def _score_cell(score: Optional[Dict[str, Any]]) -> str:
    if not score:
        return "-"
    if "error" in score:
        return "[red]err[/red]"
    value = score["value"]
    good = metrics.is_good(value, score.get("higher_is_better", True))
    return f"[{'green' if good else 'yellow'}]{value:.2f}[/]"


def _score_text(value: float) -> str:
    colour = "green" if value >= 0.8 else "yellow" if value >= 0.5 else "red"
    return f"[{colour}]{value:.2f}[/{colour}]"


def commands() -> List[click.Group]:
    return [eval_group, audit_group]
