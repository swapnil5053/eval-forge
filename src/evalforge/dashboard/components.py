"""The panel's vocabulary: labels, metrics, tables, bars, dots."""

from typing import Any

import reflex as rx

from . import styles


def label(text: str, **overrides: Any) -> rx.Component:
    return rx.el.div(text, style={**styles.LABEL, **overrides})


def metric(
    value: Any, caption: str, unit: str = "", alarm: Any = False, divider: bool = True
) -> rx.Component:
    """A dial: the number is the largest thing on screen, the caption is engraved."""
    return rx.el.div(
        rx.el.div(
            # A placeholder is not a reading: dim it so an empty window does not look
            # like a value someone should try to interpret.
            rx.el.span(
                value,
                style={
                    **styles.METRIC,
                    "color": rx.cond(value == "—", styles.TEXT_FAINT, "inherit"),
                },
            ),
            rx.cond(
                unit != "",
                rx.el.span(
                    unit,
                    style={
                        "font_family": styles.MONO,
                        "font_size": styles.FONT_BODY,
                        "color": styles.TEXT_FAINT,
                        "margin_left": "2px",
                    },
                ),
            ),
            style={"display": "flex", "align_items": "baseline"},
            color=rx.cond(alarm, styles.ERROR, styles.TEXT),
        ),
        label(caption, margin_top=styles.SPACE_2),
        style={
            "flex": "1",
            "padding": f"{styles.SPACE_4} {styles.SPACE_5} {styles.SPACE_4} 0",
            "border_right": f"1px solid {styles.BORDER}" if divider else "none",
            "min_width": "0",
        },
    )


def panel(heading: str, *children: rx.Component, **overrides: Any) -> rx.Component:
    return rx.el.div(
        label(heading, margin_bottom=styles.SPACE_3),
        *children,
        style={**styles.PANEL, "min_width": "0", **overrides},
    )


def dot(is_error: Any) -> rx.Component:
    return rx.el.span(
        style={
            "display": "inline-block",
            "width": "6px",
            "height": "6px",
            "border_radius": "50%",
            "margin_right": styles.SPACE_2,
            "vertical_align": "middle",
            "background": rx.cond(is_error, styles.ERROR, styles.OK),
        }
    )


def bars(rows: Any) -> rx.Component:
    """A horizontal bar list: the bar is the only colour, the value sits at its end."""
    return rx.el.div(
        rx.foreach(
            rows,
            lambda row: rx.el.div(
                rx.el.div(
                    rx.el.span(
                        row["key"],
                        style={
                            "font_family": styles.MONO,
                            "font_size": styles.FONT_SMALL,
                            "color": styles.TEXT_DIM,
                        },
                    ),
                    rx.el.span(
                        row["value"],
                        style={
                            "font_family": styles.MONO,
                            "font_size": styles.FONT_SMALL,
                            "color": styles.TEXT,
                        },
                    ),
                    style={
                        "display": "flex",
                        "justify_content": "space-between",
                        "margin_bottom": "3px",
                    },
                ),
                rx.cond(
                    row["width"] != "0.0%",
                    rx.el.div(
                        style={
                            "height": "3px",
                            "width": row["width"],
                            "background": styles.ACCENT,
                        }
                    ),
                    rx.el.div(style={"height": "3px"}),
                ),
                style={"margin_bottom": styles.SPACE_3},
            ),
        )
    )


def header_cell(text: str, column: str, state: Any) -> rx.Component:
    """A sortable column header. The accent marks the column currently sorting."""
    return rx.el.th(
        rx.el.span(text),
        rx.cond(
            state.sort == column,
            rx.el.span(
                rx.cond(state.descending, " ↓", " ↑"), style={"color": styles.ACCENT}
            ),
        ),
        on_click=state.sort_by(column),
        style={
            **styles.TABLE_HEADER,
            "color": rx.cond(state.sort == column, styles.TEXT_DIM, styles.TEXT_FAINT),
        },
    )


def cell(*children: Any, **overrides: Any) -> rx.Component:
    return rx.el.td(*children, style={**styles.TABLE_CELL, **overrides})


def empty_row(columns: int, message: str = "—") -> rx.Component:
    return rx.el.tr(
        rx.el.td(
            message,
            col_span=columns,
            style={
                **styles.TABLE_CELL,
                "color": styles.TEXT_FAINT,
                "padding_top": styles.SPACE_4,
            },
        )
    )


JSON_COLOURS = {
    "key": styles.ACCENT,
    "string": styles.TEXT,
    "number": styles.OK,
    "literal": styles.TEXT_DIM,
    "plain": styles.TEXT_FAINT,
}


def waterfall_track(span: Any) -> rx.Component:
    """Where this span sat inside its trace, on an axis shared by every sibling."""
    return rx.el.span(
        rx.el.span(
            style={
                "position": "absolute",
                "top": "0",
                "bottom": "0",
                "left": span["offset"],
                "width": span["width"],
                "min_width": "2px",
                "border_radius": "1px",
                "background": span["bar_colour"],
            }
        ),
        style={
            "position": "relative",
            "display": "inline-block",
            "vertical_align": "middle",
            "height": "5px",
            "width": "180px",
            "margin_left": styles.SPACE_4,
            "background": styles.BACKGROUND,
            "border_radius": "1px",
        },
    )


def json_block(parts: Any) -> rx.Component:
    """A JSON viewer built from coloured runs - no highlighting library."""
    return rx.el.pre(
        rx.foreach(
            parts,
            lambda part: rx.el.span(
                part["text"],
                style={"color": rx.match(
                    part["kind"],
                    *[(kind, colour) for kind, colour in JSON_COLOURS.items()],
                    styles.TEXT_FAINT,
                )},
            ),
        ),
        style=styles.CODE_BLOCK,
    )


def traceback_block(text: Any) -> rx.Component:
    return rx.el.pre(
        text,
        style={
            **styles.CODE_BLOCK,
            "border": "none",
            "border_left": f"2px solid {styles.ERROR}",
            "border_radius": "0",
            "color": styles.TEXT_DIM,
            "padding_left": styles.SPACE_3,
        },
    )


def token_highlight(tokens: Any) -> rx.Component:
    """Attribution preview: opacity carries the weight, the accent carries the sign."""
    return rx.el.div(
        rx.foreach(
            tokens,
            lambda token: rx.el.span(
                token["token"],
                title=token["weight"],
                style={
                    "font_family": styles.MONO,
                    "font_size": styles.FONT_SMALL,
                    "color": styles.ACCENT,
                    "opacity": token["opacity"],
                    "margin_right": "4px",
                },
            ),
        ),
        style={"line_height": "1.8"},
    )
