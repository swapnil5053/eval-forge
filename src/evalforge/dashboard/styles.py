"""Every colour, size and font the dashboard uses.

The palette and type are the same ones the landing page in ``docs/`` uses, so the
product reads as one thing: a near-black ground with a faint warm cast, one green
accent, Instrument Sans for words and JetBrains Mono for anything numeric.

Where the panel deliberately departs from the landing page is density. Marketing
pages breathe; an instrument does not. Corners stay square, padding stays tight and
rows stay 26px, because this surface is read at a glance rather than scrolled
through. Identity lives in colour and type, not in radius.

Nothing else in the dashboard writes a colour or a size literal, so retuning the
whole panel means editing this file.
"""

# Ground and surfaces, straight from the landing page's tokens.
BACKGROUND = "#0A0B0A"
SURFACE = "#101110"
SURFACE_RAISED = "#121312"
BAND = "#0D0E0D"
BORDER = "rgba(255, 255, 255, 0.07)"
BORDER_BRIGHT = "rgba(255, 255, 255, 0.14)"

TEXT = "#EDEFEC"
TEXT_DIM = "#AEB5AB"
TEXT_MUTED = "#828981"
TEXT_FAINT = "#767D74"

# One accent, used for chrome only: the active nav item, the primary chart series,
# bars, and interactive affordances on hover. It is deliberately not the "good"
# colour - see the status ramp below.
ACCENT = "#E0A33C"
ACCENT_BRIGHT = "#F0B95B"
ACCENT_MUTED = "rgba(224, 163, 60, 0.35)"

# Nothing is coloured for being fine. A healthy status, a supported claim and an
# improved score read as ordinary text; colour is reserved for what needs looking at,
# which is what makes a red row findable at a glance.
OK = TEXT_DIM
WARN = "#D99A3F"
ERROR = "#C4503E"

# Chart series, dimmest first: p50 is background information, p99 is the alarm.
SERIES = (TEXT_FAINT, TEXT_DIM, ACCENT)

MONO = "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace"
SANS = "'Instrument Sans', system-ui, -apple-system, 'Segoe UI', sans-serif"

FONT_LABEL = "9.5px"
FONT_SMALL = "11px"
FONT_BODY = "12.5px"
FONT_DATA = "12.5px"
FONT_METRIC = "30px"

SPACE_1 = "4px"
SPACE_2 = "8px"
SPACE_3 = "12px"
SPACE_4 = "16px"
SPACE_5 = "24px"

RADIUS = "2px"
SIDEBAR_WIDTH = "200px"
ROW_HEIGHT = "26px"

STYLESHEETS = [
    "https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&"
    "family=JetBrains+Mono:wght@400;500&display=swap"
]

# Small, uppercase, letter-spaced and dim: the engraved label under a panel dial.
LABEL = {
    "font_family": MONO,
    "font_size": FONT_LABEL,
    "letter_spacing": "0.12em",
    "text_transform": "uppercase",
    "color": TEXT_FAINT,
    "line_height": "1",
}

METRIC = {
    "font_family": MONO,
    "font_size": FONT_METRIC,
    "font_weight": "500",
    "color": TEXT,
    "line_height": "1",
    "letter_spacing": "-0.02em",
}

DATA = {"font_family": MONO, "font_size": FONT_DATA, "color": TEXT}
DATA_DIM = {"font_family": MONO, "font_size": FONT_DATA, "color": TEXT_DIM}
BODY = {"font_family": SANS, "font_size": FONT_BODY, "color": TEXT}

PANEL = {
    "background": SURFACE,
    "border": f"1px solid {BORDER}",
    "border_radius": RADIUS,
    "padding": SPACE_4,
}

# Data tables get square corners. Rows are separated by a single hairline, never by
# alternating fills.
TABLE = {"width": "100%", "border_collapse": "collapse", "font_family": MONO}
TABLE_HEADER = {
    **LABEL,
    "text_align": "left",
    "padding": f"{SPACE_2} {SPACE_3} {SPACE_2} 0",
    "border_bottom": f"1px solid {BORDER_BRIGHT}",
    "white_space": "nowrap",
    "cursor": "pointer",
}
TABLE_CELL = {
    "font_family": MONO,
    "font_size": FONT_DATA,
    "color": TEXT,
    "padding": f"{SPACE_2} {SPACE_3} {SPACE_2} 0",
    "border_bottom": f"1px solid {BORDER}",
    "white_space": "nowrap",
}

INPUT = {
    "background": BACKGROUND,
    "border": f"1px solid {BORDER}",
    "border_radius": RADIUS,
    "color": TEXT,
    "font_family": MONO,
    "font_size": FONT_DATA,
    "padding": f"{SPACE_1} {SPACE_2}",
    "outline": "none",
    "_focus": {"border_color": ACCENT_MUTED},
    "_placeholder": {"color": TEXT_FAINT},
}

BUTTON = {
    "background": "transparent",
    "border": f"1px solid {BORDER}",
    "border_radius": RADIUS,
    "color": TEXT_DIM,
    "font_family": MONO,
    "font_size": FONT_SMALL,
    "padding": f"{SPACE_1} {SPACE_2}",
    "cursor": "pointer",
    "_hover": {"color": ACCENT, "border_color": ACCENT_MUTED},
}

CODE_BLOCK = {
    "font_family": MONO,
    "font_size": FONT_SMALL,
    "color": TEXT_DIM,
    "background": BACKGROUND,
    "border": f"1px solid {BORDER}",
    "border_radius": RADIUS,
    "padding": SPACE_2,
    "white_space": "pre-wrap",
    "word_break": "break-word",
    "overflow_x": "auto",
    "margin": "0",
}

BASE = {
    "background": BACKGROUND,
    "color": TEXT,
    "font_family": SANS,
    "font_size": FONT_BODY,
    "-webkit-font-smoothing": "antialiased",
    "::selection": {"background": ACCENT, "color": BACKGROUND},
    "::-webkit-scrollbar": {"width": "10px", "height": "10px"},
    "::-webkit-scrollbar-track": {"background": BACKGROUND},
    "::-webkit-scrollbar-thumb": {"background": BORDER_BRIGHT, "border": f"2px solid {BACKGROUND}"},
    "::-webkit-scrollbar-thumb:hover": {"background": TEXT_FAINT},
}

# Claim verdicts, worst last: the audit view colours by severity, not by score.
VERDICT_COLOURS = {
    "SUPPORTED": OK,
    "PARTIALLY_SUPPORTED": WARN,
    "UNSUPPORTED": ERROR,
    "CONTRADICTED": "#E0533A",
}


def status_colour(status: str) -> str:
    return ERROR if status == "error" else OK


def score_colour(value: float, higher_is_better: bool = True) -> str:
    """Unmarked when the score points the good way, amber mid, red when it does not.

    The midpoint here is the same one :func:`evalforge.eval.metrics.is_good` uses; this
    adds a band above it so a strong score and a barely-passing one do not look alike.
    """
    towards_good = value if higher_is_better else 1.0 - value
    if towards_good >= 0.8:
        return OK
    return WARN if towards_good >= 0.5 else ERROR
