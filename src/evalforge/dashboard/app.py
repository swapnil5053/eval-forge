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

# Where the panel points back to: the public page this tool belongs to.
PROJECT_URL = "https://swapnil5053.github.io/eval-forge/"

# The same mark the landing page uses, inline so nothing is fetched.
FAVICON = (
    "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    "<rect width='32' height='32' fill='%230A0B0A'/>"
    "<rect x='6' y='14' width='20' height='4' fill='%23A8C97F'/></svg>"
)


def shell(body: rx.Component, route: str) -> rx.Component:
    return rx.el.div(
        rx.moment(interval=REFRESH_MS, on_change=Panel.refresh, display="none"),
        ui.backdrop(),
        _sidebar(route),
        rx.el.main(
            body,
            style={
                "position": "relative",
                "z_index": "1",
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
        # The same wordmark the landing page uses, down to the blinking caret.
        rx.el.div(
            rx.el.span("eval", style={"color": styles.TEXT}),
            rx.el.span("forge", style={"color": styles.TEXT_DIM}),
            rx.el.span(
                style={
                    "display": "inline-block",
                    "width": "7px",
                    "height": "2px",
                    "background": styles.ACCENT,
                    "margin_left": "3px",
                    "margin_bottom": "2px",
                    "vertical_align": "baseline",
                    "animation": "efBlink 1.4s steps(1) infinite",
                }
            ),
            style={
                "font_family": styles.MONO,
                "font_size": "15px",
                "font_weight": "500",
                "letter_spacing": "-0.01em",
                "padding": f"{styles.SPACE_5} {styles.SPACE_4}",
            },
        ),
        rx.el.div(*[_nav_item(name, href, route) for name, href in NAV]),
        rx.el.div(style={"flex": "1"}),
        _readout(),
        style={
            "position": "sticky",
            "top": "0",
            "z_index": "1",
            "width": styles.SIDEBAR_WIDTH,
            "min_width": styles.SIDEBAR_WIDTH,
            "height": "100vh",
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
            # Mono, like the chrome on the landing page.
            "font_family": styles.MONO,
            "font_size": styles.FONT_BODY,
            "letter_spacing": "0.02em",
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
        rx.el.a(
            "project page ↗",
            href=PROJECT_URL,
            target="_blank",
            rel="noopener",
            style={
                "display": "block",
                "margin_top": styles.SPACE_3,
                "font_family": styles.MONO,
                "font_size": styles.FONT_LABEL,
                "letter_spacing": "0.12em",
                "text_transform": "uppercase",
                "color": styles.TEXT_FAINT,
                "text_decoration": "none",
                "_hover": {"color": styles.ACCENT},
            },
        ),
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
    head_components=[
        # Without this the browser asks for /favicon.ico on every load and logs a 404.
        rx.el.link(rel="icon", href=FAVICON),
        rx.el.style(
            "body { margin: 0; }"
            "@keyframes efBlink { 0%, 49% { opacity: 1; } 50%, 100% { opacity: 0; } }"
            "@keyframes efSweep { 0% { background-position: 200% 200%; }"
            " 100% { background-position: 0% 0%; } }"
            "@media (prefers-reduced-motion: reduce) { * { animation: none !important; } }"
        )
    ],
)
for page, route, title in (
    (index, "/", "EvalForge"),
    (trace_explorer, "/traces", "EvalForge · traces"),
    (experiment_list, "/experiments", "EvalForge · experiments"),
    (dataset_list, "/datasets", "EvalForge · datasets"),
    (audit_list, "/audits", "EvalForge · audits"),
):
    app.add_page(page, route=route, title=title, on_load=Panel.open_page(route))
