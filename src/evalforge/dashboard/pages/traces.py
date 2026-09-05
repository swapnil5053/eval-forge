"""Trace explorer: a dense table that opens into a tree(1)-style span view."""

import reflex as rx

from .. import components as ui
from .. import styles
from ..state import Panel

COLUMNS = (
    ("started", "started"),
    ("name", "name"),
    ("status", "status"),
    ("spans", "spans"),
    ("latency", "latency"),
    ("tokens", "tokens"),
    ("cost", "cost"),
)


def traces() -> rx.Component:
    return rx.el.div(
        _search_bar(),
        rx.el.table(
            rx.el.thead(
                rx.el.tr(
                    rx.el.th(style={**styles.TABLE_HEADER, "width": "18px"}),
                    *[ui.header_cell(title, column, Panel) for title, column in COLUMNS],
                )
            ),
            rx.el.tbody(
                rx.cond(
                    Panel.traces,
                    rx.foreach(Panel.traces, _trace_row),
                    ui.empty_row(len(COLUMNS) + 1),
                )
            ),
            style=styles.TABLE,
        ),
        _pager(),
        style={"display": "flex", "flex_direction": "column", "gap": styles.SPACE_3},
    )


def _search_bar() -> rx.Component:
    return rx.el.div(
        rx.el.input(
            placeholder="search names, inputs, outputs",
            default_value=Panel.search,
            on_blur=Panel.set_query,
            style={**styles.INPUT, "width": "340px"},
        ),
        rx.el.span(
            Panel.page_label,
            style={"font_family": styles.MONO, "font_size": styles.FONT_SMALL,
                   "color": styles.TEXT_FAINT},
        ),
        style={
            "display": "flex",
            "align_items": "center",
            "justify_content": "space-between",
        },
    )


def _trace_row(row: rx.Var) -> rx.Component:
    expanded = Panel.expanded_trace == row["id"]
    return rx.fragment(
        rx.el.tr(
            ui.cell(
                rx.cond(expanded, "▾", "▸"),
                color=rx.cond(expanded, styles.ACCENT, styles.TEXT_FAINT),
                width="18px",
                padding_right="0",
            ),
            ui.cell(row["at"], color=styles.TEXT_DIM),
            ui.cell(row["name"]),
            ui.cell(ui.dot(row["is_error"]), rx.el.span(row["status"], color=styles.TEXT_DIM)),
            ui.cell(row["spans"], color=styles.TEXT_DIM),
            ui.cell(row["latency"]),
            ui.cell(row["tokens"], color=styles.TEXT_DIM),
            ui.cell(row["cost"], color=styles.TEXT_DIM),
            on_click=Panel.toggle_trace(row["id"]),
            style={"cursor": "pointer", "_hover": {"background": styles.SURFACE}},
        ),
        rx.cond(expanded, _span_tree(), rx.fragment()),
    )


def _span_tree() -> rx.Component:
    return rx.el.tr(
        rx.el.td(
            rx.el.div(
                rx.foreach(Panel.spans, _span_node),
                style={
                    "background": styles.SURFACE,
                    "border_left": f"2px solid {styles.ACCENT_MUTED}",
                    "padding": f"{styles.SPACE_3} {styles.SPACE_4}",
                },
            ),
            col_span=len(COLUMNS) + 1,
            style={"padding": f"0 0 {styles.SPACE_3} 0", "border_bottom": f"1px solid {styles.BORDER}"},
        )
    )


def _span_node(span: rx.Var) -> rx.Component:
    open_now = Panel.expanded_span == span["id"]
    return rx.el.div(
        rx.el.div(
            rx.el.span(span["branch"], style={"color": styles.TEXT_FAINT, "white_space": "pre"}),
            ui.dot(span["is_error"]),
            rx.el.span(span["name"], style={"color": styles.TEXT}),
            rx.el.span(
                span["type"],
                style={"color": styles.TEXT_FAINT, "margin_left": styles.SPACE_2},
            ),
            rx.el.span(
                span["latency"],
                style={"color": styles.TEXT_DIM, "margin_left": styles.SPACE_3},
            ),
            rx.cond(
                span["tokens"] != "",
                rx.el.span(
                    span["tokens"],
                    style={"color": styles.TEXT_FAINT, "margin_left": styles.SPACE_3},
                ),
            ),
            rx.cond(
                span["model"] != "",
                rx.el.span(
                    span["model"],
                    style={"color": styles.TEXT_FAINT, "margin_left": styles.SPACE_3},
                ),
            ),
            ui.waterfall_track(span),
            on_click=Panel.toggle_span(span["id"]),
            style={
                "font_family": styles.MONO,
                "font_size": styles.FONT_DATA,
                "line_height": "1.9",
                "cursor": "pointer",
                "_hover": {"background": styles.SURFACE_RAISED},
            },
        ),
        rx.cond(open_now, _span_detail(span), rx.fragment()),
    )


def _span_detail(span: rx.Var) -> rx.Component:
    return rx.el.div(
        _field("input", Panel.input_parts, span["input_preview"]),
        _field("output", Panel.output_parts, span["output_preview"]),
        rx.cond(
            span["has_error"],
            rx.el.div(
                ui.label("traceback", margin_bottom=styles.SPACE_2),
                ui.traceback_block(span["error"]),
                style={"margin_top": styles.SPACE_3},
            ),
        ),
        rx.cond(
            Panel.attribution,
            rx.el.div(
                ui.label("token attribution", margin_bottom=styles.SPACE_2),
                ui.token_highlight(Panel.attribution),
                style={"margin_top": styles.SPACE_3},
            ),
        ),
        style={
            "margin": f"{styles.SPACE_2} 0 {styles.SPACE_4} {styles.SPACE_5}",
            "padding_left": styles.SPACE_3,
            "border_left": f"1px solid {styles.BORDER}",
        },
    )


def _field(name: str, parts: rx.Var, preview: rx.Var) -> rx.Component:
    """Collapsed to an 80-character preview; the summary row opens the full JSON."""
    return rx.el.details(
        rx.el.summary(
            rx.el.span(name, style={**styles.LABEL, "margin_right": styles.SPACE_3}),
            rx.el.span(
                preview,
                style={
                    "font_family": styles.MONO,
                    "font_size": styles.FONT_SMALL,
                    "color": styles.TEXT_DIM,
                },
            ),
            style={"cursor": "pointer", "list_style": "none", "padding": "3px 0"},
        ),
        ui.json_block(parts),
        style={"margin_bottom": styles.SPACE_2},
    )


def _pager() -> rx.Component:
    return rx.el.div(
        rx.el.button(
            "prev",
            on_click=Panel.previous_page,
            disabled=~Panel.has_previous,
            style={**styles.BUTTON, "opacity": rx.cond(Panel.has_previous, "1", "0.35")},
        ),
        rx.el.button(
            "next",
            on_click=Panel.next_page,
            disabled=~Panel.has_next,
            style={**styles.BUTTON, "opacity": rx.cond(Panel.has_next, "1", "0.35")},
        ),
        style={"display": "flex", "gap": styles.SPACE_2},
    )
