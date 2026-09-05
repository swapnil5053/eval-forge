"""Experiments: runs, their per-metric means, and a side-by-side comparison."""

from typing import Dict, List

import reflex as rx

from .. import components as ui
from .. import styles
from ..state import Panel


def experiments() -> rx.Component:
    return rx.el.div(
        _table(),
        rx.cond(Panel.experiment_name != "", _detail(), rx.fragment()),
        style={"display": "flex", "flex_direction": "column", "gap": styles.SPACE_4},
    )


def _table() -> rx.Component:
    return rx.el.table(
        rx.el.thead(
            rx.el.tr(
                *[
                    rx.el.th(title, style=_header_style())
                    for title in ("", "name", "dataset", "items", "scores", "run at")
                ]
            )
        ),
        rx.el.tbody(
            rx.cond(
                Panel.experiments,
                rx.foreach(Panel.experiments, _row),
                ui.empty_row(6),
            )
        ),
        style=styles.TABLE,
    )


def _header_style() -> dict:
    return {**styles.TABLE_HEADER, "cursor": "default"}


def _row(row: rx.Var) -> rx.Component:
    open_now = Panel.experiment_name == row["name"]
    return rx.el.tr(
        ui.cell(
            rx.cond(open_now, "▾", "▸"),
            color=rx.cond(open_now, styles.ACCENT, styles.TEXT_FAINT),
            width="18px",
            padding_right="0",
        ),
        ui.cell(row["name"], color=rx.cond(open_now, styles.ACCENT, styles.TEXT)),
        ui.cell(row["dataset"], color=styles.TEXT_DIM),
        ui.cell(row["items"], color=styles.TEXT_DIM),
        ui.cell(row["summary"], color=styles.TEXT_DIM, white_space="normal"),
        ui.cell(row["at"], color=styles.TEXT_FAINT),
        on_click=Panel.open_experiment(row["name"]),
        style={"cursor": "pointer", "_hover": {"background": styles.SURFACE}},
    )


def _detail() -> rx.Component:
    return rx.el.div(
        _means(),
        _compare_bar(),
        rx.cond(Panel.comparing, _comparison(), _items()),
        style={**styles.PANEL, "display": "flex", "flex_direction": "column",
               "gap": styles.SPACE_4, "border_left": f"2px solid {styles.ACCENT_MUTED}"},
    )


def _means() -> rx.Component:
    return rx.el.div(
        rx.foreach(
            Panel.experiment_means,
            lambda row: rx.el.div(
                rx.el.div(
                    rx.el.span(row["mean"], style={**styles.METRIC, "font_size": "22px",
                                                   "color": row["colour"]}),
                ),
                ui.label(row["metric"], margin_top=styles.SPACE_2),
                ui.label(row["direction"], margin_top="3px", letter_spacing="0.04em"),
                style={"padding_right": styles.SPACE_5, "border_right": f"1px solid {styles.BORDER}",
                       "margin_right": styles.SPACE_5},
            ),
        ),
        style={"display": "flex", "flex_wrap": "wrap", "row_gap": styles.SPACE_3},
    )


def _compare_bar() -> rx.Component:
    return rx.el.div(
        ui.label("compare with"),
        rx.el.select(
            rx.el.option("—", value=""),
            rx.foreach(
                Panel.experiment_choices,
                lambda name: rx.cond(
                    name != Panel.experiment_name,
                    rx.el.option(name, value=name),
                    rx.fragment(),
                ),
            ),
            value=Panel.compare_with,
            on_change=Panel.set_compare_with,
            style={**styles.INPUT, "min_width": "200px"},
        ),
        style={"display": "flex", "align_items": "center", "gap": styles.SPACE_3},
    )


def _items() -> rx.Component:
    return rx.el.table(
        rx.el.thead(
            rx.el.tr(
                rx.el.th("item", style=_header_style()),
                rx.el.th("input", style=_header_style()),
                rx.el.th("output", style=_header_style()),
                rx.foreach(
                    Panel.experiment_metrics,
                    lambda metric: rx.el.th(
                        metric, style={**_header_style(), "text_align": "right"}
                    ),
                ),
                rx.el.th("latency", style={**_header_style(), "text_align": "right"}),
            )
        ),
        rx.el.tbody(rx.foreach(Panel.experiment_items, _item_row)),
        style=styles.TABLE,
    )


def _item_row(row: rx.Var) -> rx.Component:
    return rx.el.tr(
        ui.cell(row["id"], color=styles.TEXT_FAINT),
        ui.cell(row["input"], color=styles.TEXT_DIM, white_space="normal", max_width="220px"),
        ui.cell(
            rx.cond(
                row["has_error"],
                rx.el.span(row["error"], style={"color": styles.ERROR}),
                rx.el.span(row["output"]),
            ),
            white_space="normal",
            max_width="240px",
        ),
        # Reflex cannot infer the type of a list nested inside a dict var, so the
        # score cells are annotated on the way into the loop.
        rx.foreach(
            row["cells"].to(List[Dict[str, str]]),
            lambda cell: ui.cell(
                rx.el.span(cell["text"], title=cell["reason"], style={"color": cell["colour"]}),
                text_align="right",
            ),
        ),
        ui.cell(row["latency"], color=styles.TEXT_DIM, text_align="right"),
    )


def _comparison() -> rx.Component:
    return rx.el.table(
        rx.el.thead(
            rx.el.tr(
                rx.el.th("item", style=_header_style()),
                rx.el.th("metric", style=_header_style()),
                rx.el.th(Panel.experiment_name, style={**_header_style(), "text_align": "right"}),
                rx.el.th(Panel.compare_with, style={**_header_style(), "text_align": "right"}),
                rx.el.th("delta", style={**_header_style(), "text_align": "right"}),
            )
        ),
        rx.el.tbody(
            rx.foreach(
                Panel.comparison,
                lambda row: rx.el.tr(
                    ui.cell(row["id"], color=styles.TEXT_FAINT),
                    ui.cell(row["metric"], color=styles.TEXT_DIM),
                    ui.cell(row["left"], text_align="right"),
                    ui.cell(row["right"], text_align="right"),
                    ui.cell(row["delta"], text_align="right", color=row["colour"]),
                ),
            )
        ),
        style=styles.TABLE,
    )
