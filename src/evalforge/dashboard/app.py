"""The panel shell: fixed sidebar, scrolling main area, five-second poll."""

import reflex as rx

from . import components as ui
from . import styles
from .pages.audits import audits
from .pages.datasets import datasets
from .pages.experiments import experiments
from .pages.overview import overview
from .pages.traces import traces
from .state import REFRESH_MS, Panel

NAV = (
    ("overview", "/"),
    ("traces", "/traces"),
    ("experiments", "/experiments"),
    ("datasets", "/datasets"),
    ("audits", "/audits"),
)

BUILT = {route for _, route in NAV}


def shell(body: rx.Component, route: str) -> rx.Component:
    return rx.el.div(
        rx.moment(interval=REFRESH_MS, on_change=Panel.refresh, display="none"),
        _sidebar(route),
        rx.el.main(
            body,
            style={
                "flex": "1",
                "min_width": "0",
                "padding": styles.SPACE_5,
                "overflow_y": "auto",
                "height": "100vh",
            },
        ),
        style={"display": "flex", "background": styles.BACKGROUND, "min_height": "100vh"},
    )


def _sidebar(route: str) -> rx.Component:
    return rx.el.nav(
        rx.el.div(
            rx.el.span("EVAL", style={"color": styles.TEXT}),
            rx.el.span("FORGE", style={"color": styles.ACCENT}),
            style={
                "font_family": styles.MONO,
                "font_size": "13px",
                "letter_spacing": "0.18em",
                "padding": f"{styles.SPACE_5} {styles.SPACE_4} {styles.SPACE_5}",
            },
        ),
        rx.el.div(*[_nav_item(name, href, route) for name, href in NAV]),
        rx.el.div(style={"flex": "1"}),
        _readout(),
        style={
            "width": styles.SIDEBAR_WIDTH,
            "min_width": styles.SIDEBAR_WIDTH,
            "height": "100vh",
            "position": "sticky",
            "top": "0",
            "display": "flex",
            "flex_direction": "column",
            "background": styles.SURFACE,
            "border_right": f"1px solid {styles.BORDER}",
        },
    )


def _nav_item(name: str, href: str, route: str) -> rx.Component:
    active = href == route
    built = href in BUILT
    colour = styles.ACCENT if active else (styles.TEXT_DIM if built else styles.TEXT_FAINT)
    return rx.el.a(
        name,
        href=href if built else "#",
        style={
            "display": "block",
            "font_family": styles.SANS,
            "font_size": styles.FONT_BODY,
            "letter_spacing": "0.06em",
            "text_transform": "uppercase",
            "text_decoration": "none",
            "color": colour,
            "padding": f"{styles.SPACE_2} {styles.SPACE_4}",
            # The active marker is a lit edge, not a filled pill.
            "border_left": f"2px solid {styles.ACCENT if active else 'transparent'}",
            "cursor": "pointer" if built else "default",
            "_hover": {"color": styles.TEXT if built else colour},
        },
    )


def _readout() -> rx.Component:
    return rx.el.div(
        _readout_line("traces", Panel.footer["traces"]),
        _readout_line("updated", Panel.footer["updated"]),
        _readout_line("db", Panel.footer["size"]),
        style={
            "padding": styles.SPACE_4,
            "border_top": f"1px solid {styles.BORDER}",
        },
    )


def _readout_line(name: str, value: rx.Var) -> rx.Component:
    return rx.el.div(
        ui.label(name),
        rx.el.span(
            value,
            style={
                "font_family": styles.MONO,
                "font_size": styles.FONT_SMALL,
                "color": styles.TEXT_DIM,
            },
        ),
        style={
            "display": "flex",
            "justify_content": "space-between",
            "align_items": "center",
            "margin_bottom": styles.SPACE_2,
        },
    )


def index() -> rx.Component:
    return shell(overview(), "/")


def trace_explorer() -> rx.Component:
    return shell(traces(), "/traces")


def experiment_list() -> rx.Component:
    return shell(experiments(), "/experiments")


def dataset_list() -> rx.Component:
    return shell(datasets(), "/datasets")


def audit_list() -> rx.Component:
    return shell(audits(), "/audits")


app = rx.App(
    style=styles.BASE,
    stylesheets=styles.STYLESHEETS,
    head_components=[rx.el.style("body { margin: 0; }")],
)
for page, route, title in (
    (index, "/", "EvalForge"),
    (trace_explorer, "/traces", "EvalForge · traces"),
    (experiment_list, "/experiments", "EvalForge · experiments"),
    (dataset_list, "/datasets", "EvalForge · datasets"),
    (audit_list, "/audits", "EvalForge · audits"),
):
    app.add_page(page, route=route, title=title, on_load=Panel.open_page(route))
