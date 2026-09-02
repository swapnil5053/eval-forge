"""Overview: the whole instrument panel on one screen, no tabs."""

import reflex as rx

from .. import components as ui
from .. import styles
from ..state import Panel

CHART_HEIGHT = 150


def overview() -> rx.Component:
    return rx.el.div(
        _metrics(),
        _charts(),
        _breakdowns(),
        _errors(),
        style={"display": "flex", "flex_direction": "column", "gap": styles.SPACE_4},
    )


def _metrics() -> rx.Component:
    return rx.el.div(
        ui.metric(Panel.summary["traces"], "traces 24h"),
        ui.metric(Panel.summary["avg_latency"], "avg latency"),
        ui.metric(Panel.summary["p95_latency"], "p95 latency"),
        ui.metric(
            Panel.summary["error_rate"],
            "error rate",
            unit="%",
            alarm=Panel.summary["error_rate_high"],
        ),
        ui.metric(Panel.summary["cost"], "cost usd", unit="$", divider=False),
        style={
            "display": "flex",
            "border_bottom": f"1px solid {styles.BORDER}",
            "align_items": "stretch",
        },
    )


def _axis(data_key: str) -> rx.Component:
    return rx.recharts.x_axis(
        data_key=data_key,
        stroke=styles.BORDER_BRIGHT,
        tick_line=False,
        axis_line=True,
        tick={"fill": styles.TEXT_FAINT, "fontSize": 10, "fontFamily": styles.MONO},
        interval="preserveStartEnd",
    )


def _y_axis() -> rx.Component:
    return rx.recharts.y_axis(
        stroke=styles.BORDER_BRIGHT,
        tick_line=False,
        axis_line=False,
        width=38,
        tick={"fill": styles.TEXT_FAINT, "fontSize": 10, "fontFamily": styles.MONO},
    )


def _line(key: str, colour: str) -> rx.Component:
    return rx.recharts.line(
        data_key=key, stroke=colour, stroke_width=1.5, dot=False, type_="linear"
    )


def _charts() -> rx.Component:
    return rx.el.div(
        ui.panel(
            "trace volume · 7d",
            rx.recharts.line_chart(
                _line("traces", styles.ACCENT),
                _axis("day"),
                _y_axis(),
                rx.recharts.graphing_tooltip(**_TOOLTIP),
                data=Panel.volume,
                height=CHART_HEIGHT,
                margin={"top": 4, "right": 8, "bottom": 0, "left": 0},
            ),
        ),
        ui.panel(
            "latency percentiles · 7d",
            rx.recharts.line_chart(
                _line("p50", styles.SERIES[0]),
                _line("p95", styles.SERIES[1]),
                _line("p99", styles.SERIES[2]),
                _axis("day"),
                _y_axis(),
                rx.recharts.graphing_tooltip(**_TOOLTIP),
                data=Panel.latency,
                height=CHART_HEIGHT,
                margin={"top": 4, "right": 8, "bottom": 0, "left": 0},
            ),
            rx.el.div(
                _legend("p50", styles.SERIES[0]),
                _legend("p95", styles.SERIES[1]),
                _legend("p99", styles.SERIES[2]),
                style={"display": "flex", "gap": styles.SPACE_4, "margin_top": styles.SPACE_2},
            ),
        ),
        style=_TWO_UP,
    )


def _legend(name: str, colour: str) -> rx.Component:
    return rx.el.div(
        rx.el.span(
            style={
                "display": "inline-block",
                "width": "8px",
                "height": "1.5px",
                "background": colour,
                "margin_right": styles.SPACE_2,
                "vertical_align": "middle",
            }
        ),
        rx.el.span(name, style={"font_family": styles.MONO, "font_size": styles.FONT_LABEL,
                                "color": styles.TEXT_FAINT}),
    )


def _breakdowns() -> rx.Component:
    return rx.el.div(
        ui.panel(
            "tokens by model · 24h",
            rx.cond(
                Panel.tokens_by_model,
                ui.bars(Panel.tokens_by_model),
                _nothing(),
            ),
        ),
        ui.panel(
            "cost by function · 24h",
            rx.cond(
                Panel.cost_by_function,
                ui.bars(Panel.cost_by_function),
                _nothing(),
            ),
        ),
        style=_TWO_UP,
    )


def _nothing() -> rx.Component:
    return rx.el.div(
        "—",
        style={"font_family": styles.MONO, "font_size": styles.FONT_DATA,
               "color": styles.TEXT_FAINT},
    )


def _errors() -> rx.Component:
    """Absent when there is nothing wrong - no congratulatory empty state."""
    return rx.cond(
        Panel.errors,
        ui.panel(
            "recent errors",
            rx.el.table(
                rx.el.tbody(
                    rx.foreach(
                        Panel.errors,
                        lambda row: rx.el.tr(
                            ui.cell(row["at"], color=styles.TEXT_DIM, width="120px"),
                            ui.cell(row["short_id"], color=styles.TEXT_FAINT, width="80px"),
                            ui.cell(row["span_name"], width="160px"),
                            ui.cell(
                                row["message"],
                                color=styles.ERROR,
                                white_space="normal",
                            ),
                        ),
                    )
                ),
                style=styles.TABLE,
            ),
        ),
    )


_TWO_UP = {
    "display": "grid",
    "grid_template_columns": "1fr 1fr",
    "gap": styles.SPACE_4,
}

_TOOLTIP = {
    "content_style": {
        "background": styles.SURFACE_RAISED,
        "border": f"1px solid {styles.BORDER_BRIGHT}",
        "borderRadius": styles.RADIUS,
        "fontFamily": styles.MONO,
        "fontSize": styles.FONT_SMALL,
    },
    "item_style": {"color": styles.TEXT},
    "label_style": {"color": styles.TEXT_FAINT},
    "cursor": {"stroke": styles.BORDER_BRIGHT, "strokeWidth": 1},
}
