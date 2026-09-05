"""Datasets: what an experiment runs against."""

import reflex as rx

from .. import components as ui
from .. import styles
from ..state import Panel


def datasets() -> rx.Component:
    return rx.el.div(
        rx.el.table(
            rx.el.thead(
                rx.el.tr(
                    *[
                        rx.el.th(title, style={**styles.TABLE_HEADER, "cursor": "default"})
                        for title in ("", "name", "items", "description", "created")
                    ]
                )
            ),
            rx.el.tbody(
                rx.cond(
                    Panel.datasets,
                    rx.foreach(Panel.datasets, _row),
                    ui.empty_row(5),
                )
            ),
            style=styles.TABLE,
        ),
        rx.cond(Panel.dataset_name != "", _items(), rx.fragment()),
        style={"display": "flex", "flex_direction": "column", "gap": styles.SPACE_4},
    )


def _row(row: rx.Var) -> rx.Component:
    open_now = Panel.dataset_name == row["name"]
    return rx.el.tr(
        ui.cell(
            rx.cond(open_now, "▾", "▸"),
            color=rx.cond(open_now, styles.ACCENT, styles.TEXT_FAINT),
            width="18px",
            padding_right="0",
        ),
        ui.cell(row["name"], color=rx.cond(open_now, styles.ACCENT, styles.TEXT)),
        ui.cell(row["items"], color=styles.TEXT_DIM),
        ui.cell(row["description"], color=styles.TEXT_DIM, white_space="normal"),
        ui.cell(row["at"], color=styles.TEXT_FAINT),
        on_click=Panel.open_dataset(row["name"]),
        style={"cursor": "pointer", "_hover": {"background": styles.SURFACE}},
    )


def _items() -> rx.Component:
    return rx.el.div(
        ui.label(Panel.dataset_name, margin_bottom=styles.SPACE_3),
        rx.el.table(
            rx.el.thead(
                rx.el.tr(
                    *[
                        rx.el.th(title, style={**styles.TABLE_HEADER, "cursor": "default"})
                        for title in ("item", "input", "expected")
                    ]
                )
            ),
            rx.el.tbody(
                rx.foreach(
                    Panel.dataset_items,
                    lambda row: rx.el.tr(
                        ui.cell(row["id"], color=styles.TEXT_FAINT),
                        ui.cell(row["input"], white_space="normal"),
                        ui.cell(row["expected"], color=styles.TEXT_DIM, white_space="normal"),
                    ),
                )
            ),
            style=styles.TABLE,
        ),
        style={**styles.PANEL, "border_left": f"2px solid {styles.ACCENT_MUTED}"},
    )
