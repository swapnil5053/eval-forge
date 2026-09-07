"""Audit reports: the claim-level view of a faithfulness audit."""

import reflex as rx

from .. import components as ui
from .. import styles
from ..state import Panel


def audits() -> rx.Component:
    return rx.el.div(
        rx.el.table(
            rx.el.thead(
                rx.el.tr(
                    *[
                        rx.el.th(title, style={**styles.TABLE_HEADER, "cursor": "default"})
                        for title in (
                            "", "trace", "query", "score", "claims",
                            "unsupported", "contradicted", "at",
                        )
                    ]
                )
            ),
            rx.el.tbody(
                rx.cond(Panel.audits, rx.foreach(Panel.audits, _row), ui.empty_row(8))
            ),
            style=styles.TABLE,
        ),
        rx.cond(Panel.audit_id != "", _report(), rx.fragment()),
        style={"display": "flex", "flex_direction": "column", "gap": styles.SPACE_4},
    )


def _row(row: rx.Var) -> rx.Component:
    open_now = Panel.audit_id == row["id"]
    return rx.el.tr(
        ui.cell(
            rx.cond(open_now, "▾", "▸"),
            color=rx.cond(open_now, styles.ACCENT, styles.TEXT_FAINT),
            width="18px",
            padding_right="0",
        ),
        ui.cell(row["trace_id"], color=styles.TEXT_DIM),
        ui.cell(row["query"], white_space="normal"),
        ui.cell(row["score"], color=row["colour"], text_align="right"),
        ui.cell(row["claims"], color=styles.TEXT_DIM, text_align="right"),
        ui.cell(row["unsupported"], color=styles.ERROR, text_align="right"),
        ui.cell(
            row["contradicted"],
            color=styles.VERDICT_COLOURS["CONTRADICTED"],
            text_align="right",
        ),
        ui.cell(row["at"], color=styles.TEXT_FAINT),
        on_click=Panel.open_audit(row["id"]),
        style={"cursor": "pointer", "_hover": {"background": styles.SURFACE}},
    )


def _report() -> rx.Component:
    return rx.el.div(
        _header(),
        rx.el.div(
            rx.foreach(Panel.audit_claims, _claim),
            style={"margin_top": styles.SPACE_4},
        ),
        style={**styles.PANEL, "border_left": f"2px solid {styles.ACCENT_MUTED}"},
    )


def _header() -> rx.Component:
    return rx.el.div(
        rx.el.div(
            rx.el.span(
                Panel.audit["score"],
                style={**styles.METRIC, "color": Panel.audit["colour"]},
            ),
            ui.label("faithfulness", margin_top=styles.SPACE_2),
            style={"padding_right": styles.SPACE_5, "border_right": f"1px solid {styles.BORDER}"},
        ),
        rx.el.div(
            ui.label("query"),
            rx.el.div(
                Panel.audit["query"],
                style={**styles.DATA, "margin_top": styles.SPACE_2, "line_height": "1.5"},
            ),
            ui.label("answer", margin_top=styles.SPACE_3),
            rx.el.div(
                Panel.audit["answer"],
                style={**styles.DATA_DIM, "margin_top": styles.SPACE_2, "line_height": "1.5"},
            ),
            style={"padding_left": styles.SPACE_5, "flex": "1", "min_width": "0"},
        ),
        style={"display": "flex", "align_items": "flex-start"},
    )


def _claim(claim: rx.Var) -> rx.Component:
    """One claim: verdict colour on the left edge, evidence indented beneath it."""
    return rx.el.div(
        rx.el.div(
            rx.el.span(
                claim["verdict"],
                style={
                    "font_family": styles.MONO,
                    "font_size": styles.FONT_LABEL,
                    "letter_spacing": "0.08em",
                    "color": claim["colour"],
                    "flex": "0 0 150px",
                },
            ),
            rx.el.span(claim["claim"], style={**styles.BODY, "flex": "1", "min_width": "0"}),
            style={"display": "flex", "gap": styles.SPACE_3, "align_items": "baseline"},
        ),
        rx.cond(
            claim["rationale"] != "",
            rx.el.div(
                claim["rationale"],
                style={
                    "font_family": styles.SANS,
                    "font_size": styles.FONT_SMALL,
                    "color": styles.TEXT_DIM,
                    "margin": f"{styles.SPACE_2} 0 0 {styles.SPACE_5}",
                    "padding_left": "126px",
                },
            ),
        ),
        rx.cond(
            claim["evidence"] != "",
            rx.el.div(
                claim["evidence"],
                style={
                    "font_family": styles.MONO,
                    "font_size": styles.FONT_SMALL,
                    "color": styles.TEXT_FAINT,
                    "margin": f"{styles.SPACE_2} 0 0 {styles.SPACE_5}",
                    "padding_left": "126px",
                    "line_height": "1.5",
                },
            ),
        ),
        style={
            "padding": f"{styles.SPACE_3} 0 {styles.SPACE_3} {styles.SPACE_3}",
            "border_left": f"2px solid {claim['colour']}",
            "border_bottom": f"1px solid {styles.BORDER}",
        },
    )
